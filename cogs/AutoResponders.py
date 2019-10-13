import asyncio
import json
import random
import re
from json import JSONDecodeError

import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Lang, Utils, Questions, Emoji, Configuration
from utils.Database import AutoResponder


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
        'ignore_mod': 4
    }

    trigger_length_max = 300

    def __init__(self, bot):
        super().__init__(bot)

        self.triggers = dict()
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

                self.triggers[guild.id][trigger] = {
                    'match_list': match_list,
                    'response': response,
                    'flags': flags,
                    'responsechannelid': responder.responsechannelid
                }
        self.loaded = True

    async def list_auto_responders(self, ctx):
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_string("ar_list", server_name=ctx.guild.name))
        if len(self.triggers[ctx.guild.id].keys()) > 0:
            guild_triggers = self.triggers[ctx.guild.id]
            for trigger in guild_triggers.keys():
                trigger_obj = guild_triggers[trigger]
                flags_description = self.get_flags_description(trigger_obj)
                if trigger_obj['responsechannelid']:
                    flags_description += f"\n**\u200b \u200b **Respond in Channel: <#{trigger_obj['responsechannelid']}>"
                embed.add_field(name=f"**__trigger:__** {get_trigger_description(trigger)}", value=flags_description, inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(Lang.get_string("no_autoresponders"))

    async def choose_trigger(self, ctx):
        options = []
        keys = []
        for i in self.triggers[ctx.guild.id].keys():
            options.append(f"{len(options)} ) {get_trigger_description(await Utils.clean(i))}")
            keys.append(i)
        options = '\n'.join(options)
        prompt = f"{Lang.get_string('ar_which_trigger')}\n{options}"

        try:
            return_value = int(await Questions.ask_text(self.bot,
                                                        ctx.channel,
                                                        ctx.author,
                                                        prompt))
            if len(keys) > return_value >= 0:
                return_value = keys[return_value]
                chosen = get_trigger_description(await Utils.clean(return_value))
                await ctx.send(Lang.get_string('you_chose', value=chosen))
                return return_value
            raise ValueError
        except ValueError:
            await nope(ctx, Lang.get_string("expect_integer", min=0, max=len(keys)-1))
            raise

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
        if len(trigger) == 0:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('ar_empty_trigger')}")
        elif reply is None or reply == "":
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('ar_empty_reply')}")
        elif len(trigger) > self.trigger_length_max:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('ar_trigger_too_long')}")
        else:
            db_trigger = await get_db_trigger(ctx.guild.id, trigger)
            if db_trigger is None:
                AutoResponder.create(serverid=ctx.guild.id, trigger=trigger, response=reply)
                # self.triggers[ctx.guild.id][trigger]['response'] = reply
                await self.reload_triggers(ctx)
                await ctx.send(
                    f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('ar_added', trigger=trigger)}"
                )
            else:
                async def yes():
                    await ctx.send(Lang.get_string('ar_updating'))
                    await ctx.invoke(self.update, db_trigger, reply=reply)

                async def no():
                    await ctx.send(Lang.get_string('ar_not_updating'))

                try:
                    await Questions.ask(self.bot,
                                        ctx.channel,
                                        ctx.author,
                                        Lang.get_string('ar_override_confirmation'),
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
                f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('ar_trigger_too_long')}"
            )
        elif trigger in self.triggers[ctx.guild.id]:
            AutoResponder.get(serverid=ctx.guild.id, trigger=trigger).delete_instance()
            del self.triggers[ctx.guild.id][trigger]
            await ctx.send(
                f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('ar_removed', trigger=get_trigger_description(trigger))}"
            )
        else:
            await ctx.send(
                f"{Emoji.get_chat_emoji('NO')} {Lang.get_string('ar_not_found', trigger=get_trigger_description(trigger))}"
            )

    @autor.command(aliases=["h"])
    @commands.guild_only()
    async def help(self, ctx: commands.Context):
        await ctx.send(Lang.get_string('ar_help'))

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
        await ctx.send(f"Raw response for __{get_trigger_description(trigger)}__:\n```{row.response}```")

    @autor.command(aliases=["edit", "set"])
    @commands.guild_only()
    async def update(self, ctx: commands.Context, trigger: str = None, *, reply: str = None):
        """ar_update_help"""
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
                                             Lang.get_string("ar_prompt_response"),
                                             escape=False)

        trigger = AutoResponder.get_or_none(serverid=ctx.guild.id, trigger=trigger)
        if trigger is None:
            await ctx.send(
                f"{Emoji.get_chat_emoji('WARNING')} {Lang.get_string('ar_creating')}"
            )
            await ctx.invoke(self.create, trigger, reply=reply)
        else:
            trigger.response = reply
            trigger.save()
            # self.triggers[ctx.guild.id][trigger]['response'] = reply
            await self.reload_triggers(ctx)

            await ctx.send(
                f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('ar_updated', trigger=trigger)}"
            )

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

    @autor.command(aliases=["channel", "sc"])
    @commands.guild_only()
    async def setchannel(self, ctx: commands.Context, trigger: str = None, channel_id: int = None):
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
                                                    Lang.get_string("ar_prompt_channel_id"))

        channel_id = re.sub(r'[^\d]', '', channel_id)
        if db_trigger is None or not re.match(r'^\d+$', channel_id):
            await nope(ctx)
            return

        channel = self.bot.get_channel(int(channel_id))
        if channel_id is 0:
            await ctx.send(f"Okay, won't respond to `{get_trigger_description(trigger)}` in any channel")
        elif channel is not None:
            await ctx.send(f"Okay, I'll respond to `{get_trigger_description(trigger)}` in {channel.mention}")
        else:
            await ctx.send("No channel set.")
            return
        db_trigger.responsechannelid = channel_id
        db_trigger.save()

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
                                                    Lang.get_string('ar_which_flag', options=options)))
            if not len(flag_names) > int(flag) >= 0:
                raise ValueError

            if value is None:
                def choose(val):
                    nonlocal value
                    value = bool(val)

                await Questions.ask(self.bot,
                                    ctx.channel,
                                    ctx.author,
                                    Lang.get_string('on_or_off', subject=flag_names[flag]),
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

        is_mod = message.author.guild_permissions.ban_members
        # search guild auto-responders
        for trigger, data in self.triggers[message.channel.guild.id].items():
            # flags
            active = data['flags'][self.flags['active']]
            ignore_mod = data['flags'][self.flags['ignore_mod']]
            match_case = data['flags'][self.flags['match_case']]
            full_match = data['flags'][self.flags['full_match']]
            delete_trigger = data['flags'][self.flags['delete']]

            if not active or (is_mod and ignore_mod):
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
                    response = str(response[random.randint(0, len(response)-1)])

                # send to channel
                if data['responsechannelid']:
                    response_channel = self.bot.get_channel(data['responsechannelid'])
                else:
                    response_channel = message.channel

                await response_channel.send(
                    response.replace("@", "@\u200b").format(
                        author=message.author.mention,
                        channel=response_channel.mention,
                        link=message.jump_url
                    )
                )
                if delete_trigger:
                    await message.delete()


def setup(bot):
    bot.add_cog(AutoResponders(bot))
