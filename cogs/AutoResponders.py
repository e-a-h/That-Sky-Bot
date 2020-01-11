import asyncio
import json
import random
import re
from collections import namedtuple
from datetime import datetime
from json import JSONDecodeError

import discord
from discord.ext import commands
from discord.errors import NotFound

from cogs.BaseCog import BaseCog
from utils import Lang, Utils, Questions, Emoji, Configuration, Logging
from utils.Database import AutoResponder

mod_action = namedtuple("mod_action", "channel_id message_id response", defaults=(None, None, None))


async def nope(ctx, msg: str = None):
    msg = msg or Lang.get_string('nope')
    await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} {msg}")


async def get_db_trigger(guild_id: int, trigger: str):
    if guild_id is None or trigger is None:
        return None
    trigger = await Utils.clean(trigger, links=False)
    return AutoResponder.get_or_none(serverid=guild_id, trigger=trigger)


def get_trigger_description(trigger) -> str:
    if len(trigger) > 30:
        part_a = trigger[0:15]
        part_b = trigger[-15:]
        return f"`{part_a} ... {part_b}`"
    return trigger


class AutoResponders(BaseCog):

    flags = {
        'active': 0,
        'full_match': 1,
        'delete': 2,
        'match_case': 3,
        'ignore_mod': 4,
        'mod_action': 5
    }

    trigger_length_max = 300

    def __init__(self, bot):
        super().__init__(bot)

        self.triggers = dict()
        self.mod_actions = dict()
        self.bot.loop.create_task(self.reload_triggers())
        self.loaded = False

    async def cog_check(self, ctx):
        if not hasattr(ctx.author, 'guild'):
            return False
        return ctx.author.guild_permissions.ban_members

    def get_flag_name(self, index):
        for key, value in self.flags.items():
            if value is index:
                return key

    async def reload_triggers(self, ctx=None):
        guilds = self.bot.guilds if ctx is None else [ctx.guild]
        for guild in guilds:
            self.triggers[guild.id] = dict()
            for responder in AutoResponder.select().where(AutoResponder.serverid == guild.id):
                # interpret flags bitmask and store for reference
                flags = dict()
                for index in self.flags.values():
                    flags[index] = responder.flags & 1 << index

                # use JSON object for random response
                try:
                    # leading and trailing quotes are assumed
                    response = json.loads(responder.response[1:-1])
                except JSONDecodeError as e:
                    # not json. do not raise exception, use string instead
                    response = responder.response

                # use JSON object to require each of several triggers in any order
                try:
                    # TODO: enforce structure and depth limit. Currently written to accept 1D and 2D array of strings
                    match_list = json.loads(responder.trigger)
                    # 1D Array means a matching string will have each word in the list, in any order
                    # A list in any index of the list means any *one* word in the 2nd level list will match
                    # e.g. ["one", ["two", "three"]] will match a string that has "one" AND ("two" OR "three")
                    # "this is one of two example sentences that will match."
                    # "there are three examples and this one will match as well."
                    # "A sentence like this one will NOT match."
                except JSONDecodeError as e:
                    # not json. do not raise exception
                    match_list = None

                trigger = responder.trigger
                chance = responder.chance / 10000  # chance is 0-10,000. make it look more like a percentage

                self.triggers[guild.id][trigger] = {
                    'match_list': match_list,
                    'response': response,
                    'flags': flags,
                    'chance': chance,
                    'responsechannelid': responder.responsechannelid,
                    'listenchannelid': responder.listenchannelid
                }
        self.loaded = True

    async def list_auto_responders(self, ctx):
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_string("autoresponder/list", server_name=ctx.guild.name))
        if len(self.triggers[ctx.guild.id].keys()) > 0:
            guild_triggers = self.triggers[ctx.guild.id]
            for trigger in guild_triggers.keys():
                trigger_obj = guild_triggers[trigger]
                flags_description = self.get_flags_description(trigger_obj)
                if trigger_obj['chance'] < 1:
                    flags_description += f"\n**\u200b \u200b **Chance of response: {trigger_obj['chance']*100}%"
                if trigger_obj['responsechannelid']:
                    flags_description += f"\n**\u200b \u200b **Respond in Channel: <#{trigger_obj['responsechannelid']}>"
                if trigger_obj['listenchannelid']:
                    flags_description += f"\n**\u200b \u200b **Listen in Channel: <#{trigger_obj['listenchannelid']}>"
                embed.add_field(name=f"**__trigger:__** {get_trigger_description(trigger)}", value=flags_description, inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(Lang.get_string("autoresponder/none_set"))

    async def choose_trigger(self, ctx):
        options = []
        keys = []
        for i in self.triggers[ctx.guild.id].keys():
            options.append(f"{len(options)} ) {get_trigger_description(await Utils.clean(i))}")
            keys.append(i)
        options = '\n'.join(options)
        prompt = f"{Lang.get_string('autoresponder/which_trigger')}\n{options}"

        try:
            return_value = int(await Questions.ask_text(self.bot,
                                                        ctx.channel,
                                                        ctx.author,
                                                        prompt))
            if len(keys) > return_value >= 0:
                return_value = keys[return_value]
                chosen = get_trigger_description(await Utils.clean(return_value))
                await ctx.send(Lang.get_string('autoresponder/you_chose', value=chosen))
                return return_value
            raise ValueError
        except ValueError:
            await nope(ctx, Lang.get_string("autoresponder/expect_integer", min=0, max=len(keys)-1))
            raise

    async def validate_trigger(self, ctx, trigger):
        if len(trigger) == 0:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('autoresponder/empty_trigger')}")
        elif len(trigger) > self.trigger_length_max:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('autoresponder/trigger_too_long')}")
        else:
            return True
        return False

    async def validate_reply(self, ctx, reply):
        if reply is None or reply == "":
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('autoresponder/empty_reply')}")
            return False
        return True

    def get_flags_description(self, trigger_obj, pre=None) -> str:
        # some empty space for indent, if a prefix string is not given
        pre = pre or '**\u200b \u200b **'
        if trigger_obj['flags'][self.flags['active']]:
            flags = []
            for i, v in trigger_obj['flags'].items():
                if v:
                    flags.append(f"**{self.get_flag_name(i)}**")
            return f'{pre} Flags: ' + ', '.join(flags)
        return f"{pre} ***DISABLED***"

    async def add_mod_action(self, trigger, matched, message, response_channel, formatted_response):
        """
        :param message: Trigger message
        :param response_channel: Channel to respond in
        :param formatted_response: prepared auto-response
        :return: None
        """
        embed = discord.Embed(
            title=f"Trigger: {matched or get_trigger_description(trigger)}",
            timestamp=message.created_at,
            color=0xFF0940
        )
        embed.add_field(name='Message Author', value=message.author.mention, inline=True)
        embed.add_field(name='Channel', value=message.channel.mention, inline=True)
        embed.add_field(name='Jump link', value=f"[Go to message]({message.jump_url})", inline=True)
        contents = Utils.paginate(message.content, max_chars=1024)
        i = 0
        for chunk in contents:
            i = i + 1
            embed.add_field(name=f"Original message{ ', part '+str(i) if len(contents) > 1 else ''}", value=f"```{chunk}```", inline=False)
        embed.add_field(name='Moderator Actions', value=f"""
            Pass: {Emoji.get_emoji("YES")}
            Intervene: {Emoji.get_emoji("CANDLE")}
            Auto-Respond: {Emoji.get_emoji("WARNING")}
            DESTROY: {Emoji.get_emoji("NO")}
        """)

        # message add reactions
        sent_response = await response_channel.send(embed=embed)
        await sent_response.add_reaction(Emoji.get_emoji("YES"))
        await sent_response.add_reaction(Emoji.get_emoji("CANDLE"))
        await sent_response.add_reaction(Emoji.get_emoji("WARNING"))
        await sent_response.add_reaction(Emoji.get_emoji("NO"))

        action = mod_action(message.channel.id, message.id, formatted_response)
        self.mod_actions[sent_response.id] = action

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.triggers[guild.id] = dict()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.triggers[guild.id]
        for command in AutoResponder.select().where(AutoResponder.serverid == guild.id):
            command.delete_instance()

    @commands.group(name="autoresponder", aliases=['ar', 'auto'])
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def autor(self, ctx: commands.Context):
        """Show a list of auto-responders"""
        if ctx.invoked_subcommand is None:
            await self.list_auto_responders(ctx)

    @autor.command()
    @commands.guild_only()
    async def reload(self, ctx: commands.Context):
        await self.reload_triggers(ctx)
        await ctx.send("reloaded:")
        await self.list_auto_responders(ctx)

    @autor.command(aliases=["new", "add"])
    @commands.guild_only()
    async def create(self, ctx: commands.Context, trigger: str, *, reply: str = None):
        """Create an auto-responder. specify the trigger string and the response
        Flags are unset when initialized, so newly created responders will not be active.
        Use `autoresponder setflag` to activate
        """
        if await self.validate_trigger(ctx, trigger) and await self.validate_reply(ctx, reply):
            db_trigger = await get_db_trigger(ctx.guild.id, trigger)
            if db_trigger is None:
                AutoResponder.create(serverid=ctx.guild.id, trigger=trigger, response=reply)
                await self.reload_triggers(ctx)
                await ctx.send(
                    f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('autoresponder/added', trigger=trigger)}"
                )
            else:
                async def yes():
                    await ctx.send(Lang.get_string('autoresponder/updating'))
                    await ctx.invoke(self.update, db_trigger, reply=reply)

                async def no():
                    await ctx.send(Lang.get_string('autoresponder/not_updating'))

                try:
                    await Questions.ask(self.bot,
                                        ctx.channel,
                                        ctx.author,
                                        Lang.get_string('autoresponder/override_confirmation'),
                                        [
                                            Questions.Option('YES', handler=yes),
                                            Questions.Option('NO', handler=no)
                                        ], delete_after=True)
                except asyncio.TimeoutError:
                    pass

    @autor.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, trigger: str = None):
        """ar_remove_help"""
        if trigger is None:
            try:
                trigger = await self.choose_trigger(ctx)
            except ValueError:
                return

        trigger = await Utils.clean(trigger, links=False)
        if len(trigger) > self.trigger_length_max:
            await ctx.send(
                f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('autoresponder/trigger_too_long')}"
            )
        elif trigger in self.triggers[ctx.guild.id]:
            AutoResponder.get(serverid=ctx.guild.id, trigger=trigger).delete_instance()
            del self.triggers[ctx.guild.id][trigger]
            await ctx.send(
                f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('autoresponder/removed', trigger=get_trigger_description(trigger))}"
            )
            await self.reload_triggers(ctx)
        else:
            await ctx.send(
                f"{Emoji.get_chat_emoji('NO')} {Lang.get_string('autoresponder/not_found', trigger=get_trigger_description(trigger))}"
            )

    @autor.command(aliases=["h"])
    @commands.guild_only()
    async def help(self, ctx: commands.Context):
        await ctx.send(Lang.get_string('autoresponder/help'))

    @autor.command(aliases=["raw"])
    @commands.guild_only()
    async def getraw(self, ctx: commands.Context, trigger: str = None):
        if trigger is None:
            try:
                trigger = await self.choose_trigger(ctx)
            except ValueError:
                return

        row = AutoResponder.get_or_none(serverid=ctx.guild.id, trigger=trigger)
        if trigger is None or row is None:
            await nope(ctx)
            return
        await ctx.send(f"__Raw trigger:__\n```{trigger}```\n__Raw response:__\n```{row.response}```")

    @autor.command(aliases=["edit", "set"])
    @commands.guild_only()
    async def update(self, ctx: commands.Context, trigger: str = None, *, reply: str = None):
        """ar_update_help"""
        try:
            if trigger is None:
                try:
                    trigger = await self.choose_trigger(ctx)
                except ValueError:
                    return

            trigger = await Utils.clean(trigger, links=False)
            if reply is None:
                reply = await Questions.ask_text(self.bot,
                                                 ctx.channel,
                                                 ctx.author,
                                                 Lang.get_string("autoresponder/prompt_response"),
                                                 escape=False)

            trigger = AutoResponder.get_or_none(serverid=ctx.guild.id, trigger=trigger)
            if trigger is None:
                await ctx.send(
                    f"{Emoji.get_chat_emoji('WARNING')} {Lang.get_string('autoresponder/creating')}"
                )
                await ctx.invoke(self.create, trigger, reply=reply)
            else:
                trigger.response = reply
                trigger.save()
                await self.reload_triggers(ctx)

                await ctx.send(
                    f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('autoresponder/updated', trigger=get_trigger_description(trigger.trigger))}"
                )
        except Exception as ex:
            pass

    @autor.command(aliases=["edittrigger", "settrigger", "trigger", "st"])
    @commands.guild_only()
    async def updatetrigger(self, ctx: commands.Context, trigger: str = None, *, new_trigger: str = None):
        """ar_update_help"""
        if trigger is None:
            try:
                trigger = await self.choose_trigger(ctx)
            except ValueError:
                return

        trigger = await Utils.clean(trigger, links=False)
        if new_trigger is None:
            new_trigger = await Questions.ask_text(self.bot,
                                                   ctx.channel,
                                                   ctx.author,
                                                   Lang.get_string("autoresponder/prompt_trigger"),
                                                   escape=False)

        if self.validate_trigger(ctx, new_trigger):
            trigger = AutoResponder.get_or_none(serverid=ctx.guild.id, trigger=trigger)
            if trigger is None:
                await nope(ctx)
            else:
                trigger.trigger = new_trigger
                trigger.save()
                await self.reload_triggers(ctx)

                await ctx.send(
                    f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('autoresponder/updated', trigger=trigger)}"
                )
        else:
            await nope(ctx)

    @autor.command(aliases=["flags", "lf"])
    @commands.guild_only()
    async def listflags(self, ctx: commands.Context, trigger: str = None):
        if trigger is None:
            try:
                trigger = await self.choose_trigger(ctx)
            except ValueError:
                return

        trigger_obj = self.triggers[ctx.guild.id][trigger]
        trigger = await Utils.clean(trigger)
        await ctx.send(f"`{get_trigger_description(trigger)}`: {self.get_flags_description(trigger_obj)}")

    @autor.command(aliases=["set_chance", "chance"])
    @commands.guild_only()
    async def setchance(self, ctx: commands.Context, trigger: str = None, *, chance: float = None):
        if trigger is None:
            try:
                trigger = await self.choose_trigger(ctx)
            except ValueError:
                return

        if chance is None:
            chance = float(await Questions.ask_text(self.bot,
                                                    ctx.channel,
                                                    ctx.author,
                                                    Lang.get_string("autoresponder/prompt_chance"),
                                                    escape=False))

        try:
            db_trigger = await get_db_trigger(ctx.guild.id, trigger)
            if db_trigger is None:
                await nope(ctx)
                return

            chance = int(chance * 100)
            db_trigger.chance = chance
            db_trigger.save()
        except Exception as e:
            await Utils.handle_exception("autoresponder setchance exception", self.bot, e)
        await ctx.send(
            Lang.get_string('autoresponder/chanceset',
                            chance=chance/100,
                            trigger=get_trigger_description(trigger)))
        await self.reload_triggers(ctx)

    @autor.command(aliases=["channel", "sc"])
    @commands.guild_only()
    async def setchannel(self, ctx: commands.Context, mode: str = None, trigger: str = None, channel_id: int = None):
        if mode is None or mode not in ['respond', 'listen']:
            def choose(val):
                nonlocal mode
                mode = val

            try:
                await Questions.ask(self.bot,
                                    ctx.channel,
                                    ctx.author,
                                    Lang.get_string('autoresponder/which_mode'),
                                    [
                                        Questions.Option(f"NUMBER_1", 'Response Channel', handler=choose, args=['respond']),
                                        Questions.Option(f"NUMBER_2", 'Listen Channel', handler=choose, args=['listen'])
                                    ],
                                    delete_after=True, show_embed=True)
            except (ValueError, asyncio.TimeoutError) as e:
                return

        if trigger is None:
            try:
                trigger = await self.choose_trigger(ctx)
            except ValueError:
                return

        db_trigger = await get_db_trigger(ctx.guild.id, trigger)

        if not channel_id:
            channel_id = await Questions.ask_text(self.bot,
                                                  ctx.channel,
                                                  ctx.author,
                                                  Lang.get_string("autoresponder/prompt_channel_id", mode=mode))

        channel_id = re.sub(r'[^\d]', '', channel_id)
        if db_trigger is None or not re.match(r'^\d+$', channel_id):
            await nope(ctx)
            return

        channel = self.bot.get_channel(int(channel_id))
        if channel_id is "0":
            await ctx.send(Lang.get_string("autoresponder/channel_unset",
                                           mode=mode,
                                           trigger=get_trigger_description(trigger)))
        elif channel is not None:
            await ctx.send(Lang.get_string("autoresponder/channel_set",
                                           channel=channel.mention,
                                           mode=mode,
                                           trigger=get_trigger_description(trigger)))
        else:
            await ctx.send(Lang.get_string("autoresponder/no_channel", mode=mode))
            return
        if mode == "respond":
            db_trigger.responsechannelid = channel_id
        elif mode == "listen":
            db_trigger.listenchannelid = channel_id
        db_trigger.save()
        await self.reload_triggers(ctx)

    @autor.command(aliases=["sf"])
    @commands.guild_only()
    async def setflag(self, ctx: commands.Context, trigger: str = None, flag: int = None, value: bool = None):
        """ar_update_help"""
        db_trigger = None
        while db_trigger is None:
            if trigger is None:
                try:
                    trigger = await self.choose_trigger(ctx)
                except ValueError:
                    return

            # get db trigger based on raw trigger
            db_trigger = await get_db_trigger(ctx.guild.id, trigger)
            trigger = None

        try:
            options = []
            flag_names = []
            for i, v in self.flags.items():
                options.append(f"{v}) {i}")
                flag_names.append(i)

            if flag is None:
                options = '\n'.join(options)
                flag = int(await Questions.ask_text(self.bot,
                                                    ctx.channel,
                                                    ctx.author,
                                                    Lang.get_string('autoresponder/which_flag', options=options)))
            if not len(flag_names) > int(flag) >= 0:
                raise ValueError

            if value is None:
                def choose(val):
                    nonlocal value
                    value = bool(val)

                await Questions.ask(self.bot,
                                    ctx.channel,
                                    ctx.author,
                                    Lang.get_string('autoresponder/on_or_off', subject=flag_names[flag]),
                                    [
                                        Questions.Option(f"YES", 'On', handler=choose, args=[True]),
                                        Questions.Option(f"NO", 'Off', handler=choose, args=[False])
                                    ],
                                    delete_after=True, show_embed=True)

            if flag not in AutoResponders.flags.values():
                msg = "Invalid Flag. Try one of these:\n"
                for key, value in AutoResponders.flags.items():
                    msg += f"{value}: {key}\n"
                await ctx.send(msg)
                return

            if value:
                db_trigger.flags = db_trigger.flags | (1 << flag)
                await ctx.send(f"`{self.get_flag_name(flag)}` flag activated")
                if flag is self.flags['mod_action']:
                    await ctx.send(Lang.get_string('autoresponder/mod_action_warning'))
            else:
                db_trigger.flags = db_trigger.flags & ~(1 << flag)
                await ctx.send(f"`{self.get_flag_name(flag)}` flag deactivated")
            db_trigger.save()
            await self.reload_triggers(ctx)
        except asyncio.TimeoutError:
            pass
        except ValueError:
            await nope(ctx)

    @commands.guild_only()
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Set up message listener and respond to specific text with various canned responses"""

        prefix = Configuration.get_var("bot_prefix")
        is_boss = await self.cog_check(message)
        command_context = message.content.startswith(prefix, 0) and is_boss
        not_in_guild = not hasattr(message.channel, "guild") or message.channel.guild is None

        if message.author.bot or command_context or not_in_guild:
            return

        is_mod = message.author.guild_permissions.mute_members
        # search guild auto-responders
        for trigger, data in self.triggers[message.channel.guild.id].items():
            # flags
            active = data['flags'][self.flags['active']]
            delete_trigger = data['flags'][self.flags['delete']]
            ignore_mod = data['flags'][self.flags['ignore_mod']]
            match_case = data['flags'][self.flags['match_case']]
            full_match = data['flags'][self.flags['full_match']]
            mod_action = data['flags'][self.flags['mod_action']] and data['responsechannelid']
            chance = data['chance']

            if not active or (is_mod and ignore_mod):
                continue

            if data['listenchannelid'] and data['listenchannelid'] != message.channel.id:
                continue

            if data['match_list'] is not None:
                # full match not allowed when using list-match so this check must come first.
                words = []
                for word in data['match_list']:
                    if isinstance(word, list):
                        sub_list = []
                        for token in word:
                            sub_list.append(re.escape(token))
                        # a list of words at this level indicates one word from a list must match
                        word = f"({'|'.join(sub_list)})"
                    else:
                        word = re.escape(word)
                    # escape the words and join together as a series of look-ahead searches
                    words.append(f'(?=.*{word})')
                trigger = ''.join(words)
                re_tag = re.compile(trigger, re.IGNORECASE if not match_case else 0)
            elif full_match:
                re_tag = re.compile(rf"^{re.escape(trigger)}$", re.IGNORECASE if not match_case else 0)
            else:
                re_tag = re.compile(re.escape(trigger), re.IGNORECASE if not match_case else 0)

            match = re.search(re_tag, message.content)

            if match is not None:
                response = data['response']

                # pick from random responses
                if isinstance(response, list):
                    response = random.choice(response)

                # send to channel
                if data['responsechannelid']:
                    response_channel = self.bot.get_channel(data['responsechannelid'])
                else:
                    response_channel = message.channel

                matched = ', '.join(match.groups()) or trigger

                formatted_response = response.replace("@", "@\u200b").format(
                    author=message.author.mention,
                    channel=message.channel.mention,
                    link=message.jump_url,
                    matched=matched
                )

                m = self.bot.metrics
                m.auto_responder_count.inc()

                if mod_action:
                    await self.add_mod_action(trigger, matched, message, response_channel, formatted_response)
                else:
                    roll = random.random()
                    if chance == 1 or roll < chance:
                        await response_channel.send(formatted_response)

                if delete_trigger:
                    await message.delete()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        try:
            channel = self.bot.get_channel(event.channel_id)
            message = await channel.fetch_message(event.message_id)
            member = message.channel.guild.get_member(event.user_id)
            user_is_bot = event.user_id == self.bot.user.id
            has_permission = member.guild_permissions.mute_members  # TODO: change to role-based?
            if user_is_bot or not has_permission:
                return
            action: mod_action = self.mod_actions.pop(event.message_id)
        except (NotFound, KeyError, AttributeError) as e:
            # couldn't find channel, message, member, or action
            return
        except Exception as e:
            await Utils.handle_exception("auto-responder generic exception", self, e)
            return

        await self.do_mod_action(action, member, message, event.emoji)

    async def do_mod_action(self, action, member, message, emoji):
        """
        :param action: namedtuple mod_action to execute
        :param member: member performing the action
        :param message: message action is performed on
        :param emoji: the emoji that was added
        :return: None
        """

        try:
            trigger_channel = self.bot.get_channel(action.channel_id)
            trigger_message = await trigger_channel.fetch_message(action.message_id)
        except (NotFound, AttributeError) as e:
            trigger_message = None

        m = self.bot.metrics

        if str(emoji) == str(Emoji.get_emoji("YES")):
            # delete mod action message, leave the triggering message
            await message.delete()
            m.auto_responder_mod_pass.inc()
            return

        async def update_embed(my_message, mod):
            # replace mod action list with acting mod name and datetime
            my_embed = my_message.embeds[0]
            start = message.created_at
            react_time = datetime.utcnow()
            time_d = Utils.to_pretty_time((react_time-start).seconds)
            nonlocal trigger_message
            my_embed.set_field_at(-1, name="Handled by", value=mod.mention, inline=True)
            if trigger_message is None:
                my_embed.add_field(name="Deleted", value="Member removed message before action was taken.")
            my_embed.add_field(name="Action Used", value=emoji, inline=True)
            my_embed.add_field(name="Reaction Time", value=time_d, inline=True)
            await(my_message.edit(embed=my_embed))

        await update_embed(message, member)
        await message.clear_reactions()
        await asyncio.sleep(1)

        if str(emoji) == str(Emoji.get_emoji("CANDLE")):
            # do nothing
            m.auto_responder_mod_manual.inc()
            pass
        if str(emoji) == str(Emoji.get_emoji("WARNING")):
            # send auto-response in the triggering channel
            m.auto_responder_mod_auto.inc()
            if trigger_message is not None:
                await trigger_message.channel.send(action.response)
        if str(emoji) == str(Emoji.get_emoji("NO")):
            # delete the triggering message
            m.auto_responder_mod_delete_trigger.inc()
            if trigger_message is not None:
                await trigger_message.delete()


def setup(bot):
    bot.add_cog(AutoResponders(bot))
