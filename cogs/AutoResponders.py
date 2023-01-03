import asyncio
import collections
from dataclasses import dataclass
import json
import random
import re
from datetime import datetime
from enum import Enum
from json import JSONDecodeError

import discord
import tortoise.exceptions
from discord import AllowedMentions
from discord.ext import commands, tasks
from discord.utils import utcnow
from discord.errors import NotFound, HTTPException, Forbidden

from cogs.BaseCog import BaseCog
from utils import Lang, Utils, Questions, Emoji, Configuration, Logging
from utils.Database import AutoResponder


@dataclass
class ArPager:
    active_page: int = 0
    message: discord.Message = None


class ArFlags(Enum):
    ACTIVE = 0
    FULL_MATCH = 1
    DELETE = 2
    MATCH_CASE = 3
    IGNORE_MOD = 4
    MOD_ACTION = 5
    # 'log_only': 6,
    # 'dm_response': 7,
    # 'delete_when_trigger_deleted': 8,
    # 'delete_on_mod_respond': 9


class AutoResponders(BaseCog):
    flags = {
        'active': 0,
        'full_match': 1,
        'delete': 2,
        'match_case': 3,
        'ignore_mod': 4,
        'mod_action': 5  # ,
        # 'log_only': 6,
        # 'dm_response': 7,
        # 'delete_when_trigger_deleted': 8,
        # 'delete_on_mod_respond': 9
    }

    trigger_length_max = 300
    action_expiry_default = 86400

    def __init__(self, bot):
        super().__init__(bot)
        self.triggers = dict()
        self.mod_messages = dict()
        self.mod_action_expiry = dict()
        self.ar_list = dict()
        self.ar_list_messages = dict()
        self.loaded = False

    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.init_guild(guild)
        self.reload_mod_actions()
        await self.reload_triggers()
        self.clean_old_autoresponders.start()

    def cog_unload(self):
        self.clean_old_autoresponders.cancel()

    async def init_guild(self, guild):
        self.triggers[guild.id] = dict()
        self.mod_messages[guild.id] = dict()
        self.ar_list[guild.id] = []
        self.ar_list_messages[guild.id] = dict()
        self.mod_action_expiry[guild.id] = Configuration.get_var(
            f'auto_action_expiry_seconds_{guild.id}',
            self.action_expiry_default
        )

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.triggers[guild.id]
        del self.mod_messages[guild.id]
        del self.ar_list[guild.id]
        del self.ar_list_messages[guild.id]
        del self.mod_action_expiry[guild.id]
        try:
            Configuration.del_persistent_var(f"mod_messages_{guild.id}")
            del Configuration.MASTER_CONFIG[f'auto_action_expiry_seconds_{guild.id}']
            Configuration.save()
        except Exception as e:
            Logging.error(f"Could not save config when removing auto_action_expiry_seconds_{guild.id}")
        await AutoResponder.filter(serverid=guild.id).delete()

    @staticmethod
    def get_trigger_description(trigger) -> str:
        if (len(trigger) + 5) > 30:
            part_a = trigger[0:15]
            part_b = trigger[-15:]
            return f"`{part_a} ... {part_b}`"
        return trigger

    @staticmethod
    async def nope(ctx, msg: str = None):
        msg = msg or Lang.get_locale_string('common/nope', ctx)
        await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} {msg}")

    @staticmethod
    async def get_db_trigger(guild_id: int, trigger: str):
        if guild_id is None or trigger is None:
            return None
        # trigger = await Utils.clean(trigger, links=False)
        return await AutoResponder.get_or_none(serverid=guild_id, trigger=trigger)

    async def cog_check(self, ctx):
        if ctx.guild is None:
            return False
        return ctx.author.guild_permissions.ban_members

    def get_flag_name(self, index):
        for key, value in self.flags.items():
            if value is index:
                return key

    def reload_mod_actions(self, ctx=None):
        guilds = self.bot.guilds if ctx is None else [ctx.guild]
        for guild in guilds:
            self.mod_messages[guild.id] = dict()
            saved_mod_messages = Configuration.get_persistent_var(f"mod_messages_{guild.id}")
            if saved_mod_messages:
                for channel_id, actions in saved_mod_messages.items():
                    # Convert json str keys to int
                    channel_id = int(channel_id)
                    if channel_id not in self.mod_messages[guild.id]:
                        self.mod_messages[guild.id][channel_id] = dict()
                    for message_id, action in actions.items():
                        message_id = int(message_id)
                        self.mod_messages[guild.id][channel_id][message_id] = action

    @tasks.loop(seconds=60)
    async def clean_old_autoresponders(self):
        for guild_id, channels in self.mod_messages.items():
            for channel_id, messages in channels.items():
                for message_id, action in dict(messages).items():
                    now = datetime.now().timestamp()
                    if (now - action['event_datetime']) > self.mod_action_expiry[guild_id]:
                        #  expire very old mod action messages --- remove reacts and add "expired" react
                        try:
                            del self.mod_messages[guild_id][channel_id][message_id]
                            Configuration.set_persistent_var(f"mod_messages_{guild_id}", self.mod_messages[guild_id])

                            guild = self.bot.get_guild(guild_id)
                            channel = guild.get_channel(channel_id)
                            message = await channel.fetch_message(message_id)
                            await message.clear_reactions()

                            # replace mod action list with acting mod name and datetime
                            my_embed = message.embeds[0]
                            start = message.created_at
                            react_time = utcnow()
                            time_d = Utils.to_pretty_time((react_time - start).seconds)
                            my_embed.set_field_at(-1, name="Expired", value=f'No action taken for {time_d}', inline=True)
                            edited_message = await message.edit(embed=my_embed)
                            await edited_message.add_reaction(Emoji.get_emoji("SNAIL"))
                        except Exception as e:
                            pass
                        pass

    async def reload_triggers(self, ctx=None):
        guilds = self.bot.guilds if ctx is None else [ctx.guild]
        for guild in guilds:
            self.triggers[guild.id] = dict()
            for responder in await AutoResponder.filter(serverid=guild.id).order_by("id"):
                # interpret flags bitmask and store for reference
                flags = dict()
                for index in self.flags.values():
                    flags[index] = responder.flags & 1 << index

                # use JSON object for random response
                try:
                    response = json.loads(responder.response)
                except JSONDecodeError as e:
                    try:
                        # leading and trailing quotes are checked
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

                try:
                    if self.triggers[guild.id][trigger]:
                        await Logging.bot_log(f"Duplicate trigger: {responder.id}) {trigger}")
                except KeyError as e:
                    pass

                self.triggers[guild.id][trigger] = {
                    'id': responder.id,
                    'match_list': match_list,
                    'response': response,
                    'flags': flags,
                    'chance': chance,
                    'responsechannelid': responder.responsechannelid,
                    'listenchannelid': responder.listenchannelid
                }
        self.loaded = True

    async def list_auto_responders(self, ctx):
        """
        Embed Limits

        Total Characters In Embed: 6000
        Total Fields: 25
        Field Name: 256
        Field Value: 1024
        Footer Text: 2048
        Author Name: 256
        Title: 256
        Description: 2048
        Embeds Per Message: 10

        General Limits

        Username: 80
        Message Content: 2000
        Message Files: 10
        """

        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("autoresponder/list", ctx, server_name=ctx.guild.name))

        if len(self.triggers[ctx.guild.id].keys()) > 0:
            guild_triggers = self.triggers[ctx.guild.id]

            my_list = []
            for trigger in guild_triggers.keys():
                trigger_obj = guild_triggers[trigger]
                flags_description = self.get_flags_description(trigger_obj, "**\u200b \u200b **")
                if trigger_obj['chance'] < 1:
                    flags_description += f"\n**\u200b \u200b ** Chance of response: {trigger_obj['chance']*100}%"
                if trigger_obj['responsechannelid']:
                    flags_description += f"\n**\u200b \u200b ** Respond in Channel: <#{trigger_obj['responsechannelid']}>"
                if trigger_obj['listenchannelid']:
                    flags_description += f"\n**\u200b \u200b ** Listen in Channel: <#{trigger_obj['listenchannelid']}>"
                ar_line = f"__**[{trigger_obj['id']}]**__ {self.get_trigger_description(trigger)}\n{flags_description}"
                my_list.append(ar_line)

            list_page = []
            self.ar_list[ctx.guild.id] = []
            for line in my_list:
                # split to groups of 10, max 2000 char
                if len(list_page) == 8 or len(''.join(list_page) + line + 50*'_') > 2000:
                    self.ar_list[ctx.guild.id].append(list_page)
                    list_page = []
                list_page.append(line)
            if list_page:
                # one more page to attach
                self.ar_list[ctx.guild.id].append(list_page)

            embed.add_field(name="page", value=f"1 of {len(self.ar_list[ctx.guild.id])}", inline=False)
            list_message = await ctx.send(embed=embed,
                                          content='\n'.join(self.ar_list[ctx.guild.id][0]),
                                          allowed_mentions=AllowedMentions.none())
            for emoji in ['LEFT', 'RIGHT']:
                await list_message.add_reaction(Emoji.get_emoji(emoji))
            self.ar_list_messages[ctx.guild.id][list_message.id] = ArPager(0, list_message)
        else:
            await ctx.send(Lang.get_locale_string("autoresponder/none_set", ctx))

    async def choose_trigger(self, ctx, trigger):
        if trigger is not None:
            try:
                # check for trigger by db id
                my_id = int(trigger)
                trigger_by_id = self.find_trigger_by_id(ctx.guild.id, my_id)
                if trigger_by_id is not None:
                    # TODO: detect trigger that matches id and offer a choice
                    return trigger_by_id
            except ValueError:
                if trigger in self.triggers[ctx.guild.id].keys():
                    return trigger
                msg = Lang.get_locale_string('autoresponder/not_found', ctx, trigger=self.get_trigger_description(trigger))
                await ctx.send(f"{Emoji.get_chat_emoji('NO')} {msg}")
                raise

        options = []
        keys = dict()
        options.append(f"{Lang.get_locale_string('autoresponder/available_triggers', ctx)}")
        prompt_messages = []

        async def clean_dialog():
            nonlocal prompt_messages
            for msg in prompt_messages:
                try:
                    await msg.delete()
                    await asyncio.sleep(0.1)
                except:
                    pass

        for trigger_string, data in self.triggers[ctx.guild.id].items():
            available_triggers = '\n'.join(options)
            option = f"{data['id']} ) {self.get_trigger_description(await Utils.clean(trigger_string))}"
            if len(f"{available_triggers}\n{option}") > 1000:
                prompt_messages.append(await ctx.send(available_triggers))  # send current options, save message
                options = ["**...**"]  # reinitialize w/ "..." continued indicator
            options.append(option)
            keys[data['id']] = trigger_string
        options = '\n'.join(options)
        prompt_messages.append(await ctx.send(options))  # send current options, save message
        prompt = Lang.get_locale_string('autoresponder/which_trigger', ctx)

        try:
            return_value = int(await Questions.ask_text(self.bot,
                                                        ctx.channel,
                                                        ctx.author,
                                                        prompt,
                                                        locale=ctx,
                                                        delete_after=True))
            if return_value in keys.keys():
                return_value = keys[return_value]
                chosen = self.get_trigger_description(await Utils.clean(return_value))
                await ctx.send(Lang.get_locale_string('autoresponder/you_chose', ctx, value=chosen))
                await clean_dialog()
                return return_value
            raise ValueError
        except (ValueError, asyncio.TimeoutError):
            await clean_dialog()
            key_dump = ', '.join(str(x) for x in keys)
            await self.nope(ctx, Lang.get_locale_string("autoresponder/expect_integer", ctx, keys=key_dump))
            raise

    async def validate_trigger(self, ctx, trigger):
        """
        Tranform trigger into validated JSON string

        :param trigger: the trigger to evaluate
        return: JSON string on success, False on failure
        """
        if len(trigger) == 0:
            msg = Lang.get_locale_string('autoresponder/empty_trigger', ctx)
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {msg}")
        elif len(trigger) > self.trigger_length_max:
            msg = Lang.get_locale_string('autoresponder/trigger_too_long', ctx)
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {msg}")
        elif trigger in self.triggers[ctx.guild.id]:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} Trigger exists already. Duplicates not allowed.")
        else:
            p1 = re.compile(r"(\[|, )'")
            p2 = re.compile(r"'(, |\])")
            fixed = p1.sub(r'\1"', trigger)
            fixed = p2.sub(r'"\1', fixed)
            try:
                trigger_obj = json.loads(fixed)
                return fixed
            except json.decoder.JSONDecodeError as e:
                return trigger
        return False

    async def validate_reply(self, ctx, reply):
        if reply is None or reply == "":
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_locale_string('autoresponder/empty_reply', ctx)}")
            return False
        return True

    def get_flags_description(self, trigger_obj, pre=None) -> str:
        # some empty space for indent, if a prefix string is not given
        pre = pre or '**\u200b \u200b **'
        if trigger_obj['flags'][self.flags['active']]:
            flags = []
            for i, v in trigger_obj['flags'].items():
                if v:
                    flags.append(f"{self.get_flag_name(i)}")
            return f'{pre} Flags: **' + ', '.join(flags) + '**'
        return f"{pre} ***DISABLED***"

    async def add_mod_action(self, trigger, matched, message, response_channel, formatted_response):
        """
        message: Trigger message
        response_channel: Channel to respond in
        formatted_response: prepared auto-response
        """
        embed = discord.Embed(
            title=f"Trigger: {matched or self.get_trigger_description(trigger)}",
            timestamp=message.created_at,
            color=0xFF0940
        )
        embed.add_field(name='Message Author', value=message.author.mention, inline=True)
        embed.add_field(name='Channel', value=message.channel.mention, inline=True)
        embed.add_field(name='Jump link', value=f"[Go to message]({message.jump_url})", inline=True)
        contents = Utils.paginate(message.content, max_chars=900)
        i = 0
        for chunk in contents:
            i = i + 1
            embed.add_field(
                name=f"Original message{ ', part '+str(i) if len(contents) > 1 else ''}",
                value=f"```{chunk}```",
                inline=False)
        embed.add_field(name='Moderator Actions', value=f"""
            Pass: {Emoji.get_emoji("YES")}
            Intervene: {Emoji.get_emoji("CANDLE")}
            Auto-Respond: {Emoji.get_emoji("WARNING")}
            DESTROY: {Emoji.get_emoji("NO")}
        """)

        # message add reactions
        # try a few times to send message if it fails
        tries = 0
        max_tries = 10
        sent_response = None
        while tries < max_tries:
            try:
                sent_response = await response_channel.send(embed=embed)
                break
            except Exception as e:
                tries = tries + 1
                if tries == max_tries:
                    await Utils.handle_exception("failed to send mod-action message", self.bot, e)
                    return

        for action_emoji in ("YES", "CANDLE", "WARNING", "NO"):
            tries = 0
            while tries < max_tries:
                try:
                    await sent_response.add_reaction(Emoji.get_emoji(action_emoji))
                    break
                except Exception as e:
                    tries = tries + 1
                    if tries == max_tries:
                        await Utils.handle_exception(f"failed to add {action_emoji} react to mod-action message", self.bot, e)

        # a record of the event
        record = {"channel_id": message.channel.id,
                  "message_id": message.id,
                  "formatted_response": formatted_response,
                  "event_datetime": datetime.now().timestamp()}

        guild_id = response_channel.guild.id

        # init dict where necessary
        if response_channel.id not in self.mod_messages[guild_id]:
            self.mod_messages[guild_id][response_channel.id] = dict()

        self.mod_messages[guild_id][response_channel.id][sent_response.id] = record
        Configuration.set_persistent_var(f"mod_messages_{guild_id}", self.mod_messages[guild_id])

    @commands.group(name="autoresponder", aliases=['ar', 'auto'])
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def autor(self, ctx: commands.Context):
        """Show a list of autoresponder tags and their flags"""
        if ctx.invoked_subcommand is None:
            await self.list_auto_responders(ctx)

    @autor.command(aliases=['setactionexpiration'])
    @commands.guild_only()
    async def set_action_expiry_seconds(self, ctx, expiry_seconds: int = 0):
        """
        Set the amount of time (in seconds) after which unused mod-action messages expire.

        expiry_seconds: Time in seconds. (e.g. 3600 for one hour, 86400 for one day) Default is 1 day.
        """
        if expiry_seconds == 0:
            expiry_seconds = self.action_expiry_default

        old_exp = self.mod_action_expiry[ctx.guild.id]
        exp = Utils.to_pretty_time(expiry_seconds)
        if old_exp == expiry_seconds:
            await ctx.send(f"mod action message expiration time is already {exp}")
            return
        try:
            # save to configuration and local var last in case saving config raises error
            Configuration.MASTER_CONFIG[f'auto_action_expiry_seconds_{ctx.guild.id}'] = expiry_seconds
            Configuration.save()
            self.mod_action_expiry[ctx.guild.id] = expiry_seconds
            await ctx.send(f"Configuration saved. Autoresponder mod action messages are now valid for {exp}")
        except Exception as e:
            await ctx.send(f"Failed while saving configuration. check the logs...")

    @autor.command()
    @commands.guild_only()
    async def reload(self, ctx: commands.Context):
        """Reload all autoresponsders for the current guild from database"""
        await self.reload_triggers(ctx)
        await ctx.send("reloaded:")
        await self.list_auto_responders(ctx)

    @autor.command(aliases=["new", "add"])
    @commands.guild_only()
    async def create(self, ctx: commands.Context, trigger: str, *, reply: str = None):
        """
        Add a new trigger/response

        Specify the trigger string and the response.
        Flags are unset when initialized, so newly created responders will not be active.
        Use `autoresponder setflag` to activate

        trigger: The trigger to respond to. Must be quoted if spaces, and «[["ULTRA-QUOTED"]]» for lists
            «["one", "two"]» will match a message with one **AND** two
            «[["one", "two"]]» will match a message with one **OR** two
            «[["one", "two"],["three", "four"]]» will match "one three" or "one four" or "two three" or "two four"
        reply: string or ["group"] that may include tokens {author}, {channel}, and {link}
            Grouped string indicates random responses.
            All auto-responses can include these tokens (include curly braces):
            {author} mentions the user who triggered
            {channel} mentions the channel in which response was triggered
            {link} links to the message that triggered response
        """
        trigger = await self.validate_trigger(ctx, trigger)
        if trigger is not False and await self.validate_reply(ctx, reply):
            db_trigger = await self.get_db_trigger(ctx.guild.id, trigger)
            if db_trigger is None:
                row = await AutoResponder.create(serverid=ctx.guild.id, trigger=trigger, response=reply)
                await self.reload_triggers(ctx)
                added_message = Lang.get_locale_string('autoresponder/added', ctx,
                                                       trigger=trigger, trigid=row.id)
                await ctx.send(
                    f"{Emoji.get_chat_emoji('YES')} {added_message}"
                )
            else:
                async def yes():
                    await ctx.send(Lang.get_locale_string('autoresponder/updating', ctx))
                    await ctx.invoke(self.update, db_trigger, reply=reply)

                async def no():
                    await ctx.send(Lang.get_locale_string('autoresponder/not_updating', ctx))

                try:
                    await Questions.ask(self.bot,
                                        ctx.channel,
                                        ctx.author,
                                        Lang.get_locale_string('autoresponder/override_confirmation', ctx),
                                        [
                                            Questions.Option('YES', handler=yes),
                                            Questions.Option('NO', handler=no)
                                        ], delete_after=True, locale=ctx)
                except asyncio.TimeoutError:
                    await self.nope(ctx)

    def find_trigger_by_id(self, guild_id, trigger_id):
        for trigger, data in self.triggers[guild_id].items():
            if data['id'] == trigger_id:
                return trigger
        return None

    @autor.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, trigger: str = None):
        """
        Remove a trigger/response.

        trigger: Optionally name the trigger to select. If trigger is omitted, bot dialog will request it.
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        try:
            # trigger = await Utils.clean(trigger, links=False)
            ar_row = await AutoResponder.get(serverid=ctx.guild.id, trigger=trigger)
            await ar_row.delete()
            del self.triggers[ctx.guild.id][trigger]
            msg = Lang.get_locale_string('autoresponder/removed', ctx, trigger=self.get_trigger_description(trigger))
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {msg}")
            await self.reload_triggers(ctx)
        except tortoise.exceptions.MultipleObjectsReturned:
            await ctx.send(f"Something wrong in the database... too many matches to trigger ```{trigger}```")
        except tortoise.exceptions.DoesNotExist:
            await ctx.send(f"I didn't find a matching AutoResponder with trigger ```{trigger}```")
        except Exception as e:
            await Utils.handle_exception("unknown AR Remove exception", self.bot, e)

    @autor.command(aliases=["raw"])
    @commands.guild_only()
    async def getraw(self, ctx: commands.Context, trigger: str = None):
        """
        View raw trigger/response text for a given autoresponder

        trigger: Optionally name the trigger to select. If trigger is omitted, bot dialog will request it.
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        row = await AutoResponder.get_or_none(serverid=ctx.guild.id, trigger=trigger)
        if trigger is None or row is None:
            await self.nope(ctx)
            return

        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("autoresponder/raw", ctx, server_name=ctx.guild.name))

        embed.add_field(name="Raw trigger", value=trigger, inline=False)

        response_parts = collections.deque(row.response)
        value = ""
        i = 1
        header = ""
        while response_parts:
            header = "Raw response" if i == 1 else f"Raw response (part {i})"
            value = value + response_parts.popleft()
            if len(value) > 1000:
                embed.add_field(name=header, value=value, inline=False)
                value = ""
                i = i + 1
        if value:
            embed.add_field(name=header, value=value, inline=False)

        await ctx.send(embed=embed)

    @autor.command(aliases=["edit", "set"])
    @commands.guild_only()
    async def update(self, ctx: commands.Context, trigger: str = None, *, reply: str = None):
        """
        Edit a response

        trigger: Optionally name the trigger to select. If trigger is omitted, bot dialog will request it.
        reply: The new response you want to save for the selected trigger.
            All auto-responses can include these tokens (include curly braces):
            {author} mentions the user who triggered
            {channel} mentions the channel in which response was triggered
            {link} links to the message that triggered response
        """
        try:
            try:
                trigger = await self.choose_trigger(ctx, trigger)
            except (ValueError, asyncio.TimeoutError):
                return

            # trigger = await Utils.clean(trigger, links=False)
            if reply is None:
                try:
                    reply = await Questions.ask_text(self.bot,
                                                     ctx.channel,
                                                     ctx.author,
                                                     Lang.get_locale_string("autoresponder/prompt_response", ctx),
                                                     escape=False,
                                                     locale=ctx)
                except asyncio.TimeoutError as e:
                    return

            trigger = await AutoResponder.get_or_none(serverid=ctx.guild.id, trigger=trigger)
            if trigger is None:
                await ctx.send(
                    f"{Emoji.get_chat_emoji('WARNING')} {Lang.get_locale_string('autoresponder/creating', ctx)}"
                )
                await ctx.invoke(self.create, trigger, reply=reply)
            else:
                trigger.response = reply
                await trigger.save()
                await self.reload_triggers(ctx)

                msg = Lang.get_locale_string('autoresponder/updated',
                                             ctx,
                                             trigger=self.get_trigger_description(trigger.trigger))
                await ctx.send(f"{Emoji.get_chat_emoji('YES')} {msg}")
        except Exception as ex:
            pass

    @autor.command(aliases=["edittrigger", "settrigger", "trigger", "st"])
    @commands.guild_only()
    async def updatetrigger(self, ctx: commands.Context, trigger: str = None, *, new_trigger: str = None):
        """
        Update tan autoresponder trigger

        trigger: The trigger to edit (must be quoted string if spaces)
        new_trigger: The new trigger to replace the old (no need for quotes)
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        # trigger = await Utils.clean(trigger, links=False)
        if new_trigger is None:
            try:
                new_trigger = await Questions.ask_text(self.bot,
                                                       ctx.channel,
                                                       ctx.author,
                                                       Lang.get_locale_string("autoresponder/prompt_trigger", ctx),
                                                       escape=False,
                                                       locale=ctx)
            except asyncio.TimeoutError as e:
                # empty trigger emits message when validated below. pass exception
                pass

        new_trigger = await self.validate_trigger(ctx, new_trigger)
        if new_trigger is not False:
            trigger = await AutoResponder.get_or_none(serverid=ctx.guild.id, trigger=trigger)
            if trigger is None:
                await self.nope(ctx)
            else:
                trigger.trigger = new_trigger
                await trigger.save()
                await self.reload_triggers(ctx)

                await ctx.send(
                    f"{Emoji.get_chat_emoji('YES')} {Lang.get_locale_string('autoresponder/updated', ctx, trigger=new_trigger)}"
                )

    @autor.command(aliases=["flags", "lf"])
    @commands.guild_only()
    async def listflags(self, ctx: commands.Context, trigger: str = None):
        """
        List settings for a trigger/response

        trigger: Optionally name the trigger to select. If trigger is omitted, bot dialog will request it.
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        trigger_obj = self.triggers[ctx.guild.id][trigger]
        trigger = await Utils.clean(trigger)
        await ctx.send(f"`{self.get_trigger_description(trigger)}`: {self.get_flags_description(trigger_obj)}")

    @autor.command(aliases=["set_chance", "chance"])
    @commands.guild_only()
    async def setchance(self, ctx: commands.Context, trigger: str = None, *, chance: float = None):
        """Set the probability for matching message to trigger a response

        trigger: Trigger text
        chance: Probability
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        if chance is None:
            try:
                chance = float(await Questions.ask_text(self.bot,
                                                        ctx.channel,
                                                        ctx.author,
                                                        Lang.get_locale_string("autoresponder/prompt_chance", ctx),
                                                        escape=False,
                                                        locale=ctx))
            except asyncio.TimeoutError as e:
                return

        try:
            db_trigger = await self.get_db_trigger(ctx.guild.id, trigger)
            if db_trigger is None:
                await self.nope(ctx)
                return

            chance = int(chance * 100)
            db_trigger.chance = chance
            await db_trigger.save()
        except Exception as e:
            await Utils.handle_exception("autoresponder setchance exception", self.bot, e)
        await ctx.send(
            Lang.get_locale_string('autoresponder/chanceset', ctx,
                                   chance=chance/100,
                                   trigger=self.get_trigger_description(trigger)))
        await self.reload_triggers(ctx)

    @autor.command(aliases=["channel", "sc", "listen_in", "respond_in", "li", "ri"])
    @commands.guild_only()
    async def setchannel(self, ctx: commands.Context, trigger: str = None, channel_id: int = None, mode: str = None):
        """
        Set a response channel for a trigger

        mode: [listen|respond]
        trigger: Trigger text
        channel_id: Channel ID to listen/respond in
        """
        respond = 'respond'
        listen = 'listen'
        # check aliases for mode
        if ctx.invoked_with in ('listen_in', 'li'):
            mode = listen
        elif ctx.invoked_with in ('respond_in', 'ri'):
            mode = respond
        if mode is None or mode not in [respond, listen]:
            def choose(val):
                nonlocal mode
                mode = val

            try:
                await Questions.ask(self.bot,
                                    ctx.channel,
                                    ctx.author,
                                    Lang.get_locale_string('autoresponder/which_mode', ctx),
                                    [
                                        Questions.Option(f"NUMBER_1",
                                                         'Response Channel',
                                                         handler=choose,
                                                         args=[respond]),
                                        Questions.Option(f"NUMBER_2",
                                                         'Listen Channel',
                                                         handler=choose,
                                                         args=[listen])
                                    ],
                                    delete_after=True, show_embed=True, locale=ctx)
            except (ValueError, asyncio.TimeoutError) as e:
                return

        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        db_trigger = await self.get_db_trigger(ctx.guild.id, trigger)

        if channel_id is None:
            try:
                channel_id = await Questions.ask_text(self.bot,
                                                      ctx.channel,
                                                      ctx.author,
                                                      Lang.get_locale_string("autoresponder/prompt_channel_id", ctx, mode=mode),
                                                      locale=ctx)
            except asyncio.TimeoutError as e:
                return

        channel_id = re.sub(r'[^\d]', '', str(channel_id))
        if db_trigger is None or not re.match(r'^\d+$', channel_id):
            await self.nope(ctx)
            return

        channel = self.bot.get_channel(int(channel_id))
        if channel_id == '0':
            await ctx.send(Lang.get_locale_string("autoresponder/channel_unset", ctx,
                                                  mode=mode,
                                                  trigger=self.get_trigger_description(trigger)))
        elif channel is not None:
            await ctx.send(Lang.get_locale_string("autoresponder/channel_set", ctx,
                                                  channel=channel.mention,
                                                  mode=mode,
                                                  trigger=self.get_trigger_description(trigger)))
        else:
            await ctx.send(Lang.get_locale_string("autoresponder/no_channel", ctx, mode=mode))
            return
        if mode == respond:
            db_trigger.responsechannelid = channel_id
        elif mode == listen:
            db_trigger.listenchannelid = channel_id
        await db_trigger.save()
        await self.reload_triggers(ctx)

    @autor.command(aliases=["sf"])
    @commands.guild_only()
    async def setflag(self, ctx: commands.Context, trigger: str = None, flag: int = None, value: bool = None):
        """
        Set an on/off option for a trigger/response

        trigger: Optionally name the trigger to select. If trigger is omitted, bot dialog will request it.
        flag: Flag number. Available flags:
            0: Active/Inactive
            1: Full Match
            2: Delete triggering message
            3: Match Case
            4: Ignore Mod
            5: Mod Action
        value: Boolean, on/off 1/0 true/false
        """
        db_trigger = None
        while db_trigger is None:
            try:
                trigger = await self.choose_trigger(ctx, trigger)
            except (ValueError, asyncio.TimeoutError):
                return

            # get db trigger based on raw trigger
            db_trigger = await self.get_db_trigger(ctx.guild.id, trigger)
            trigger = None

        try:
            options = []
            flag_names = []
            for i, v in self.flags.items():
                options.append(f"{v}) {i}")
                flag_names.append(i)

            if flag is None:
                options = '\n'.join(options)
                flag = int(await Questions.ask_text(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    Lang.get_locale_string('autoresponder/which_flag', ctx, options=options),
                    locale=ctx))
            if not len(flag_names) > int(flag) >= 0:
                raise ValueError

            if value is None:
                def choose(val):
                    nonlocal value
                    value = bool(val)

                await Questions.ask(self.bot,
                                    ctx.channel,
                                    ctx.author,
                                    Lang.get_locale_string('autoresponder/on_or_off', ctx, subject=flag_names[flag]),
                                    [
                                        Questions.Option(f"YES", 'On', handler=choose, args=[True]),
                                        Questions.Option(f"NO", 'Off', handler=choose, args=[False])
                                    ],
                                    delete_after=True, show_embed=True, locale=ctx)

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
                    await ctx.send(Lang.get_locale_string('autoresponder/mod_action_warning', ctx))
            else:
                db_trigger.flags = db_trigger.flags & ~(1 << flag)
                await ctx.send(f"`{self.get_flag_name(flag)}` flag deactivated")
            await db_trigger.save()
            await self.reload_triggers(ctx)
        except asyncio.TimeoutError:
            pass
        except ValueError:
            await self.nope(ctx)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Set up message listener and respond to specific text with various canned responses"""

        # check these first to avoid conflicts/exceptions
        not_in_guild = not hasattr(message.channel, "guild") or message.channel.guild is None
        if message.author.bot or not_in_guild:
            return

        prefix = Configuration.get_var("bot_prefix")
        can_command = await self.cog_check(message)
        command_context = message.content.startswith(prefix, 0) and can_command
        in_ignored_channel = False  # TODO: commands for global ignore channels, populate with channels

        if command_context or in_ignored_channel:
            return

        is_mod = message.author.guild_permissions.mute_members
        # search guild auto-responders

        if message.channel.guild.id not in self.triggers:
            # Guild not initialized or AR items empty? Ignore.
            return

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

            def add_bounds(my_word):
                if re.match(r'\w', my_word[0]):
                    my_word = rf"\b{my_word}"
                if re.match(r'\w', my_word[-1]):
                    my_word = rf"{my_word}\b"
                return my_word

            if data['match_list'] is not None:
                # full match done as whole word match per item in list when using list-match
                words = []
                for word in data['match_list']:
                    if isinstance(word, list):
                        sub_list = []
                        for token in word:
                            token = re.escape(token)
                            if full_match:
                                token = add_bounds(token)
                            sub_list.append(token)
                        # a list of words at this level indicates one word from a list must match
                        word = f"({'|'.join(sub_list)})"
                    else:
                        word = re.escape(word)
                        if full_match:
                            word = add_bounds(word)
                    # escape the words and join together as a series of look-ahead searches
                    words.append(f'(?=.*{word})')
                trigger = ''.join(words)
                parsed_trigger = trigger
            elif full_match:
                parsed_trigger = rf"^{re.escape(trigger)}$"
            else:
                parsed_trigger = re.escape(trigger)

            # replace escaped spaces with whitespace character class for multiline matching
            parsed_trigger = re.sub(r'\\ ', r'\\s+', parsed_trigger)
            # ignorecase is set by flag. dotall is not optional
            re_tag = re.compile(parsed_trigger, flags=(re.I if not match_case else 0) | re.S)
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
                    matched=matched,
                    trigger_message=message.content
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
                    try:
                        await message.delete()
                    except NotFound as e:
                        # Message deleted by another bot
                        pass
                    except (Forbidden, HTTPException) as e:
                        # maybe discord error.
                        await Utils.handle_exception("ar failed to delete", self.bot, e)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        action = None
        message = None

        try:
            channel = self.bot.get_channel(event.channel_id)
            my_guild = self.bot.get_guild(channel.guild.id)
            member = my_guild.get_member(event.user_id)
            user_is_bot = event.user_id == self.bot.user.id
            has_permission = member.guild_permissions.mute_members  # TODO: change to role-based?
            if user_is_bot or not has_permission:
                return

            if event.message_id in self.ar_list_messages[channel.guild.id]:
                await self.update_list_message(self.ar_list_messages[channel.guild.id][event.message_id], event)
                return

            if event.message_id in self.mod_messages[channel.guild.id][channel.id]:
                action = self.mod_messages[channel.guild.id][channel.id].pop(event.message_id)
                message = await channel.fetch_message(event.message_id)
                Configuration.set_persistent_var(f"mod_messages_{channel.guild.id}", self.mod_messages[channel.guild.id])

        except (NotFound, KeyError, AttributeError, HTTPException) as e:
            # couldn't find channel, message, member, or action
            return
        except Exception as e:
            await Utils.handle_exception("auto-responder generic exception", self.bot, e)
            return

        if action:
            await self.do_mod_action(action, member, message, event.emoji)

    async def update_list_message(self, my_pager: ArPager, event):
        direction = 0
        if str(event.emoji) == str(Emoji.get_emoji("RIGHT")):
            direction = 1
        elif str(event.emoji) == str(Emoji.get_emoji("LEFT")):
            direction = -1
        # Updating a list message
        if direction == 0:
            return

        page = my_pager.active_page
        try:
            guild_id = my_pager.message.channel.guild.id
            my_ar_list = self.ar_list[guild_id]
            step = 1 if direction > 0 else -1
            next_page = (my_pager.active_page + step) % len(my_ar_list)
            embed = my_pager.message.embeds[0]
            embed.set_field_at(-1, name="page", value=f"{next_page+1} of {len(self.ar_list[guild_id])}", inline=False)
            page = next_page
            await my_pager.message.remove_reaction(event.emoji, self.bot.get_user(event.user_id))
            edited_message = await my_pager.message.edit(content='\n'.join(my_ar_list[next_page]), embed=embed)
            my_pager.message = edited_message
        except Exception as e:
            await Utils.handle_exception('AR Pager Failed', self.bot, e)
        my_pager.active_page = page

    async def do_mod_action(self, action, member, message, emoji):
        """
        action: dict - saved action to execute
        member: member performing the action
        message: message action is performed on
        emoji: the emoji that was added
        """

        # record = {"channel_id": message.channel.id,
        #           "message_id": message.id,
        #           "formatted_response": formatted_response,
        #           "event_datetime": datetime.now().timestamp()}

        try:
            trigger_channel = self.bot.get_channel(action['channel_id'])
            trigger_message = await trigger_channel.fetch_message(action['message_id'])
        except (NotFound, HTTPException, AttributeError) as e:
            trigger_message = None

        m = self.bot.metrics

        if str(emoji) == str(Emoji.get_emoji("YES")):
            # delete mod action message, leave the triggering message
            await message.delete()
            m.auto_responder_mod_pass.inc()
            return

        await message.clear_reactions()

        # replace mod action list with acting mod name and datetime
        my_embed = message.embeds[0]
        start = message.created_at
        react_time = utcnow()
        time_d = Utils.to_pretty_time((react_time-start).seconds)
        my_embed.set_field_at(-1, name="Handled by", value=member.mention, inline=True)
        if trigger_message is None:
            my_embed.add_field(name="Deleted", value=":snail: message removed before action was taken.")
        my_embed.add_field(name="Action Used", value=emoji, inline=True)
        my_embed.add_field(name="Reaction Time", value=time_d, inline=True)
        edited_message = await message.edit(embed=my_embed)

        if str(emoji) == str(Emoji.get_emoji("CANDLE")):
            # do nothing
            m.auto_responder_mod_manual.inc()
            pass
        if str(emoji) == str(Emoji.get_emoji("WARNING")):
            # send auto-response in the triggering channel
            m.auto_responder_mod_auto.inc()
            if trigger_message is not None:
                # todo: remove formatting from on_message, move it here
                await trigger_message.channel.send(
                    action['formatted_response'])
        if str(emoji) == str(Emoji.get_emoji("NO")):
            # delete the triggering message
            m.auto_responder_mod_delete_trigger.inc()
            if trigger_message is not None:
                await trigger_message.delete()


async def setup(bot):
    await bot.add_cog(AutoResponders(bot))
