import random
from typing import Optional, Union, Literal

import discord
from discord import CategoryChannel, DMChannel, ForumChannel, Message, HTTPException, NotFound, Forbidden, TextChannel, Thread
from discord.abc import PrivateChannel, Messageable

from sky import Skybot
from utils import Utils, Logging, Emoji
from utils.AutoResponderFlags import ArFlags
from utils.AutoResponderRule import ArRule
from utils.Database import AutoResponseType, AutoResponderChannelType


class ArEvent:
    verbose = False

    def __init__(self,
                 bot: Skybot,
                 guild_id: int,
                 channel_id: int,
                 message_id: int,
                 author_id: int,
                 event_time: float,
                 matched: str,
                 content: str,
                 ar_id: int,
                 response_channel_id: int = 0,
                 response_id: int = 0,
                 *,
                 trigger_message: Optional[Message] = None,
                 rule: Optional[ArRule] = None):
        """Model representing data collected when an auto-responder match is triggered

        Parameters
        ----------
        bot
        guild_id
        channel_id
        message_id
        author_id
        event_time
            Timestamp indicating when trigger was hit
        matched
            String of matching tokens
        content
            The body of the triggering message
        ar_id
            The database id for the matching trigger row
        response_channel_id
        response_id
        trigger_message
            The message that triggered a match
        """
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.author_id = author_id
        self.event_time = event_time
        self.matched = matched
        self.content = content
        self.autoresponder_id = ar_id
        self.response_channel_id = response_channel_id
        self.response_id = response_id
        self.trigger_message = trigger_message
        self.rule = rule
        self.mod_action_channel_id = None

        # TODO: store public response here and use for future_delete

        if self.trigger_message is None:
            trigger_channel = self.bot.get_channel(channel_id)
            if (trigger_channel and
                    not isinstance(trigger_channel, ForumChannel) and
                    not isinstance(trigger_channel, CategoryChannel) and
                    not isinstance(trigger_channel, PrivateChannel)):
                self.trigger_message = trigger_channel.get_partial_message(message_id)
        # trigger_message may not be set

    @staticmethod
    async def from_message(bot,
                           message: discord.Message,
                           matched: str,
                           rule: ArRule):
        """Constructs an instance based on a message that matched a rule.
        Perform initial logic, logging, and messaging.

        Parameters
        ----------
        bot
        message
        matched
        rule

        Returns
        -------
        ArEvent|None
        """
        event_time = message.created_at.timestamp()
        my_event = ArEvent(
            bot,
            message.guild.id if message.guild else 0,
            message.channel.id,
            message.id,
            message.author.id,
            event_time,
            matched,
            message.content,
            rule.id,
            trigger_message=message
        )
        my_event.rule = rule
        await my_event.get_response_channel()

        # Increment metrics after response channel is confirmed
        m = my_event.bot.metrics
        m.auto_responder_count.inc()

        # send logging where configured
        await my_event.send_log_response()

        if my_event.rule.flag_is_set(ArFlags.LOG_ONLY):
            # Logging was completed, no further action allowed.
            return None

        await my_event.send_mod_response()

        if my_event.rule and my_event.rule.flag_is_set(ArFlags.DELETE):
            try:
                if my_event.trigger_message:
                    await my_event.trigger_message.delete()
            except NotFound:
                # Maybe trigger_message was deleted by bot (e.g. censored) or by user
                pass
            except (Forbidden, HTTPException) as e:
                # maybe discord error.
                await Utils.handle_exception("ar failed to delete", e)

        return my_event

    @staticmethod
    def from_dict(bot, data: dict):
        return ArEvent(bot, **data)

    def as_dict(self) -> dict:
        return {
            'guild_id': self.guild_id,
            'channel_id': self.channel_id,
            'message_id': self.message_id,
            'author_id': self.author_id,
            'event_time': self.event_time,
            'matched': self.matched,
            'content': self.content,
            'ar_id': self.autoresponder_id,
            'response_id': self.response_id,
            'response_channel_id': self.response_channel_id
        }

    def get_channel_ids(self, channel_type: AutoResponderChannelType) -> list[int]:
        if not self.rule:
            return []
        if channel_type == AutoResponderChannelType.listen:
            return self.rule.listen_channels
        if channel_type == AutoResponderChannelType.response:
            return self.rule.response_channels
        if channel_type == AutoResponderChannelType.log:
            return self.rule.log_channels
        if channel_type == AutoResponderChannelType.ignore:
            return self.rule.ignored_channels
        if channel_type == AutoResponderChannelType.mod:
            return self.rule.mod_channels
        # catch-all should not be reachable normally because all types are handled
        Logging.error(f"get_channel_ids: unknown channel type {channel_type}")
        return []

    async def get_response_channel(self) -> Optional[Union[TextChannel, Thread, DMChannel]]:
        # find optionally configured mod action channel
        try:
            self.mod_action_channel_id = self.get_channel_ids(AutoResponderChannelType.response)[0]
        except (KeyError, IndexError):
            pass

        # Choose where to publicly respond
        rule = await self.get_rule()
        response_channel = None
        self.response_channel_id = 0

        if rule.flag_is_set(ArFlags.DM_RESPONSE):
            try:
                user = self.bot.get_user(self.author_id)
                if user:
                    response_channel = await user.create_dm()
                    self.response_channel_id = response_channel.id
                else:
                    await Utils.guild_log(self.guild_id, f"AR Failed to find user `{self.author_id}` to DM")
            except (Forbidden, HTTPException):
                # DMs are closed or communication failed. Respond in self.response_channel_id if one is set. log DM failure
                # log DM failure and do not proceed
                await Utils.guild_log(
                    self.guild_id,
                    f"AR Failed to DM. Matched:{self.matched} "
                    f"{self.trigger_message.jump_url if self.trigger_message else '[no message jump link]'}"
                    f"```{self.content}```")
        else:
            if not rule.flag_is_set(ArFlags.MOD_ACTION):
                try:
                    self.response_channel_id = self.get_channel_ids(AutoResponderChannelType.response)[0]
                    this_channel = self.bot.get_channel(self.response_channel_id)
                    if isinstance(this_channel, (TextChannel, Thread, DMChannel)):
                        response_channel = this_channel
                except IndexError:
                    pass
            if not response_channel:
                if self.trigger_message:
                    this_channel = self.trigger_message.channel
                    if isinstance(this_channel, (TextChannel, Thread)):
                        # DM channel is not configured. Respond in the triggering channel
                        response_channel = this_channel
                        self.response_channel_id = this_channel.id
                else:
                    await Utils.guild_log(
                        self.guild_id,
                        f"No response channel set and no triggering message for AR event\n"
                        f"```{self.as_dict()}```")
        return response_channel

    async def fetch_trigger_message(self) -> discord.Message:
        if not isinstance(self.trigger_message, discord.Message):
            channel = self.bot.get_channel(self.channel_id)
            try:
                if (channel and
                        not isinstance(channel, ForumChannel) and
                        not isinstance(channel, CategoryChannel) and
                        not isinstance(channel, PrivateChannel)):
                    self.trigger_message = await channel.fetch_message(self.message_id)
                else:
                    raise ValueError(f"Invalid channel type for AR event: {type(channel)}")
            except NotFound:
                Logging.info(f"fetch not found: "
                             f"{self.trigger_message.jump_url if self.trigger_message else '[no message jump link]'}")
                raise
            except Forbidden:
                Logging.info(f"not allowed to fetch message "
                             f"{self.trigger_message.jump_url if self.trigger_message else '[no message jump link]'}")
                raise
            except HTTPException:
                await Utils.guild_log(
                    self.guild_id, f"AutoresponderEvent failed to find trigger message {self.message_id}")
                raise
        return self.trigger_message

    async def get_rule(self) -> ArRule:
        if not self.rule:
            self.rule = await ArRule.fetch_rule(self.guild_id, self.autoresponder_id)
        if not isinstance(self.rule, ArRule):
            Logging.error(f"Invalid rule type for event {self.autoresponder_id}: {type(self.rule)}")
            raise TypeError(f"Expected ArRule, got {type(self.rule)}")
        return self.rule

    async def get_formatted_responses(self, response_type: AutoResponseType) -> list[str]:
        rule = await self.get_rule()
        responses = rule.get_raw_responses(response_type)
        output = []
        for response in responses:
            output.append(await self.format_response(str(response)))
        return output

    async def get_formatted_response(self, response_type: AutoResponseType) -> Optional[str]:
        rule = await self.get_rule()
        response = rule.get_random_response(response_type)
        if response:
            return await self.format_response(str(response))
        return None

    async def format_response(self, raw_response: str) -> str:
        if (self.trigger_message and
                self.trigger_message.channel and
                isinstance(self.trigger_message.channel, TextChannel)):
            channel_mention = self.trigger_message.channel.mention
        else:
            channel_mention = "[unknown channel]"

        return str(raw_response).replace("@", "@\u200b").format(
            link=self.trigger_message.jump_url if self.trigger_message else '[missing link]',
            author=self.get_author_mention(),
            channel=channel_mention,
            trigger_message=await Utils.clean(self.content),
            matched=self.matched)

    def get_author_mention(self) -> str:
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return "[Unknown Author]"
        author = guild.get_member(self.author_id)
        if not author:
            return "[Unknown Author]"
        return author.mention

    async def has_mod_action(self):
        rule = await self.get_rule()
        if rule.flag_is_set(ArFlags.MOD_ACTION):
            return False
        if not self.mod_action_channel_id:
            return False
        return True

    async def send_public_response(self, force=False):
        """Attempt to send a formatted response to triggering message

        Returns
        -------
        response_message: Message|None
        """
        rule = await self.get_rule()
        roll = random.random()
        if force or rule.chance == 1 or roll < rule.chance:
            response_str = await self.get_formatted_response(AutoResponseType.public)
            if not response_str:
                return None
            try:
                response_channel = await self.get_response_channel()
                if response_channel is None:
                    return None

                reply_set = rule.flag_is_set(ArFlags.USE_REPLY)
                trigger_message = await self.fetch_trigger_message()
                channel_valid = response_channel.id == trigger_message.id
                my_message = self.trigger_message
                my_args = {}
                if reply_set and channel_valid:
                    my_args["reference"] = my_message
                public_response = await response_channel.send(response_str, **my_args)
            except Forbidden:
                await self.log_failure_message(response_str)
                return None
            return public_response
        return None

    async def log_failure_message(self, response_str):
        """log failure to send response

        Parameters
        ----------
        response_str: str
            The body of the message that failed to send
        """
        channel_mention = "[unknown channel]"
        response_channel = await self.get_response_channel()
        if response_channel:
            if isinstance(response_channel, DMChannel):
                recipient = response_channel.recipient
                if recipient is not None:
                    channel_mention = f"DM to {recipient.mention}"
                else:
                    channel_mention = f"DM channel id {response_channel.id}"
            else:
                channel_mention = response_channel.mention

        context_msg = f"Response in channel {channel_mention} failed"

        content_cleaned = await Utils.clean(self.content)
        # truncate messages if needed
        response_limit = 512
        content_limit = 1024
        truncate_str = " ..."
        msg_short = content_cleaned
        response_short = response_str

        if len(content_cleaned) > content_limit:
            msg_short = content_cleaned[:content_limit - len(truncate_str)] + truncate_str
        if len(response_str) > response_limit:
            response_short = response_str[:response_limit - len(truncate_str)] + truncate_str

        fail_msg = await Utils.guild_log(
            self.guild_id,
            f"`{self.matched}` in message {self.trigger_message.jump_url if self.trigger_message else '[unknown message]'}\n"
            f"{self.get_author_mention()} said:"
            f"```{msg_short}```"
            f"{context_msg}: ```{response_short}```")

        if not fail_msg:
            # log guild log failure
            await Logging.bot_log(
                f"autoresponder failed to send a dm, and found "
                f"no guild log channel in server {self.guild_id}")
            # no dm channel or guild log. no further response

    async def get_defaulted_log_channels(self, default=False) -> list[TextChannel]:
        """Find a channel to log in, and optionally default to guild log

        Parameters
        ----------
        default
            Allow defaulting

        Returns
        -------
        logging_channels
            List of channel IDs to use for logging
        """
        rule = await self.get_rule()
        log_channels: list[Optional[TextChannel]] = []

        for c in self.get_channel_ids(AutoResponderChannelType.log):
            my_channel = Utils.BOT.get_channel(c)
            if isinstance(my_channel, TextChannel):
                log_channels.append(my_channel)

        if not log_channels and (rule.flag_is_set(ArFlags.LOG_ONLY) or default):
            # Logging channel is not set, but the log_only flag is active or defaulting is enabled. use guild log
            default_log_channel = await Utils.get_guild_log_channel(self.guild_id)
            log_channels = [await Utils.get_guild_log_channel(self.guild_id)]
        return [x for x in log_channels if x is not None]

    def get_mod_response_channels(self) -> list[Messageable]:
        output = []
        for c in self.get_channel_ids(AutoResponderChannelType.mod):
            this_channel = Utils.BOT.get_channel(c)
            if this_channel:
                output.append(this_channel)
        return output

    async def send_mod_action_message(self) -> Optional[Message]:
        try:
            msg = await self.fetch_trigger_message()
        except (ValueError, NotFound, HTTPException, Forbidden) as e:
            await Logging.bot_log(f"send_mod_action_message failed: {e}")
            return None

        if not self.mod_action_channel_id:
            return None

        response_channel = self.bot.get_channel(self.mod_action_channel_id)
        if not isinstance(response_channel, TextChannel):
            return None

        rule = await self.get_rule()
        channel = msg.channel

        embed = discord.Embed(
            title=f"Trigger: {self.matched or rule.short_description('')}",
            timestamp=msg.created_at,
            color=0xFF0940
        )
        embed.add_field(name='Message Author', value=msg.author.mention, inline=True)
        if isinstance(channel, (TextChannel, Thread)):
            embed.add_field(name='Channel', value=channel.mention, inline=True)
        embed.add_field(name='Jump link', value=f"[Go to message]({msg.jump_url})", inline=True)
        Utils.pages_to_embed(msg.content, embed, "Original Message")
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
        mod_action_msg = None
        while tries < max_tries:
            try:
                mod_action_msg = await response_channel.send(embed=embed)
                break
            except Exception as e:
                tries = tries + 1
                if tries == max_tries:
                    await Utils.handle_exception(f"failed to send mod-action message {tries} times", e)
                    return None

        for action_emoji in ("YES", "CANDLE", "WARNING", "NO"):
            tries = 0
            while tries < max_tries and mod_action_msg:
                try:
                    await mod_action_msg.add_reaction(Emoji.get_emoji(action_emoji))
                    break
                except HTTPException as e:
                    tries = tries + 1
                    if tries == max_tries:
                        await Utils.handle_exception(f"mod-action react {action_emoji} failed {tries} times", e)
        return mod_action_msg

    async def send_mod_response(self):
        """Send mod response based on responses configured for this event's ruleset"""
        mod_response_channels = self.get_mod_response_channels()

        if not mod_response_channels:
            # If there are no channels, no mod responses will be sent
            return

        for my_channel in mod_response_channels:
            my_responses = await self.get_formatted_responses(AutoResponseType.mod)
            if not my_responses:
                return
            response = "\n".join([f"* {x}" for x in my_responses]) if len(my_responses) > 1 else my_responses[0]
            await my_channel.send(response)

    async def send_log_response(self):
        """Send log response based on responses configured for this event's ruleset"""
        # Do not default. If no channels are configured and no log messages are configured, no logging will be done
        log_channels = await self.get_defaulted_log_channels(False)

        if not log_channels:
            # No log channels, and logging is not forced. Do not log.
            return

        my_responses = []
        # prefer log_response > mod_response > response
        try:
            my_responses = await self.get_formatted_responses(AutoResponseType.log)
            if self.verbose:
                log_responses = "\n".join(my_responses)
                Logging.info(f"send_log_response - formatted log responses:\n{log_responses}")
            if not my_responses:
                if not log_channels:
                    # No log channels, no log responses, don't log anything
                    return
                # log channel set, so raise value error to force fetching *something* to log
                raise ValueError
        except (IndexError, ValueError):
            try:
                my_responses = await self.get_formatted_responses(AutoResponseType.public)
                if self.verbose:
                    log_responses = "\n".join(my_responses)
                    Logging.info(f"send_log_response - logging from formatted pub responses:\n{log_responses}")
            except IndexError:
                pass

        my_responses: list[str] = [x for x in my_responses if x]  # weed out empty responses

        if not my_responses:
            await Utils.guild_log(
                self.guild_id,
                f"Autoresponder {self.autoresponder_id} has no configured logging responses")
            return

        if not log_channels:
            # Log channel is needed now and may be empty. Default to guild log if necessary
            log_channels = await self.get_defaulted_log_channels(True)

        # send to log channel(s)
        response = "\n".join([f"* {x}" for x in my_responses]) if len(my_responses) > 1 else my_responses[0]
        for log_channel in log_channels:
            await log_channel.send(response)


class ArEventFactory:
    @staticmethod
    async def evaluate_event(bot, message, rule: ArRule, author_is_mod) -> Optional[ArEvent]:
        """Evaluate conditions for attempting to match an ArRule. If conditions are met, search for matches.

        Parameters
        ----------
        bot
        message
        rule
        author_is_mod

        Returns
        -------
        ArEvent|None
        """
        if not rule.flag_is_set(ArFlags.ACTIVE) or (author_is_mod and rule.flag_is_set(ArFlags.IGNORE_MOD)):
            return None

        if rule.listen_channels and message.channel.id not in rule.listen_channels:
            return None

        if message.channel.id in rule.ignored_channels:
            return None

        # TODO: remove get_global_ignore_channels and replace with access to stored ignore_channels
        a, b, global_ignore_channel_ids, d = await ArRule.get_global_ignore_channels(bot, rule.guild_id)
        if message.channel.id in global_ignore_channel_ids:
            return None

        matched = rule.find_match(message)
        if not matched:
            return None

        matched = ', '.join(matched) or rule.ar_row.trigger
        return await ArEvent.from_message(bot, message, matched, rule)
