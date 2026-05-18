"""A module defining the ArRule dataclass, which encapsulates the logic and properties associated with
an AutoResponder rule.

This module includes methods for matching message content against predefined patterns, retrieving responses,
and managing additional metadata such as response probabilities, guild-specific settings, and channel
configurations. Additionally, it encompasses utility functions for fetching rule-related data from the
database and constructing rule objects from database rows.
"""
import json
import random
import re
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Optional

from discord import Message, TextChannel
from tortoise.contrib.pydantic import pydantic_model_creator
from tortoise.exceptions import NoValuesFetched, OperationalError, IntegrityError, TransactionManagementError, \
    MultipleObjectsReturned, DoesNotExist

from utils import Logging, Utils
from utils.AutoResponderFlags import ArFlags
from utils.Constants import URL_MATCHER, DISCORD_INDENT
from utils.Database import AutoResponder, AutoResponderChannelType, AutoResponseType, AutoResponse, AutoResponderChannel
from utils.Logging import TCol


@dataclass
class ArRule:
    """
    Represents an AutoResponder rule used in a guild.

    This class encapsulates the configuration for auto-response mechanisms,
    handling patterns to match, responses, and operational flags. It is structured
    to process incoming messages, determine if a pattern matches, and provide
    appropriate responses based on its configuration.

    Attributes
    ----------
    id : int
        Unique identifier for the AutoResponder rule.
    match_list : list of str
        List of string patterns to match against messages.
    response : list of str
        List of response messages or patterns triggered by this rule.
    responses : dict of str to a list of AutoResponse
        Mapping of response type strings to a list of active AutoResponse objects.
    flags : ArFlags
        Flags representing settings and configurations for specific rule behavior.
    chance : float
        Probability (between 0 and 1) that a response will be given when a match is found.
    guild_id : int
        The guild ID associated with this rule.
    listen_channels : list of int
        List of channel IDs where this rule listens for messages.
    response_channels : list of int
        List of channel IDs where the rule sends responses.
    log_channels : list of int
        List of channel IDs where log messages are sent.
    ignored_channels : list of int
        List of channel IDs that this rule will ignore.
    mod_channels : list of int
        List of channel IDs where special moderator responses are sent.
    ar_row : AutoResponder
        Database row object associated with this rule.
    verbose : bool
        Indicates if verbose logging is enabled (default is False).
    """
    id: int
    match_list: Optional[list[str]]
    response: list[str]
    responses: dict[str, list[AutoResponse]]
    flags: ArFlags
    chance: float
    guild_id: int
    listen_channels: list[int]
    response_channels: list[int]
    log_channels: list[int]
    ignored_channels: list[int]
    mod_channels: list[int]
    ar_row: AutoResponder
    verbose: bool = False

    def find_match(self, message: Message):
        """
        Determine if the given message matches the rule's pattern list. Each term in the pattern list
        is checked, and all patterns in the rule's list must match to trigger the rule.

        Parameters
        ----------
        message : Message
            The message to be checked.

        Returns
        -------
        list of str
            A list of matched substrings within the content of the message. If any pattern fails to match,
            the function returns False.
        """
        matched = []
        words = self.get_match_list()
        match_case = ArFlags.MATCH_CASE in self.flags

        for word in words:
            if ArRule.verbose:
                Logging.info(f"\n\tpattern:\n\t\t{word}")

            re_tag = re.compile(word, flags=(re.I if not match_case else 0) | re.S)
            needle = re_tag.search(str(message.content))

            if needle is None:
                # each word in list(words) must match. The list may contain a single pattern, or many.
                # Any failing search means AR will ignore this message
                matched = False
                break

            matched.append(needle[0])  # include the complete match. capture groups are not expected
            if ArRule.verbose:
                Logging.info(f"\n\tpattern:\n\t\t{word}\n\tmatched in message:\n\t\t{message.content}")

        if self.verbose:
            Logging.info(f"ARTD find_match\ncontent: {message.content}\nmatched: {matched}")
        return matched

    def get_match_list(self) -> list:
        """
        Generates a list of match patterns based on given triggers, flags, and match lists.

        This method constructs a list of regular expression patterns to match words or
        phrases based on the object's `match_list`, `flags`, and additional parameters.
        It supports handling full word matches, multi-word synonyms, and adding word
        boundaries or escape sequences as required. The constructed patterns are intended
        to facilitate flexible matching of messages.

        Returns
        -------
        list of str
            A list of regex pattern strings that can be used for matching based on the
            object's configuration.

        Notes
        -----
        - When the `FULL_MATCH` flag is enabled, word boundaries are added to match exact
          words (e.g., 'word' will not match 'words' or 'sword').
        - Multi-synonym matching within sublists is processed such that one word from
          the sublist must match (e.g., ['cat', 'dog'] will produce '(cat|dog)').
        - Escaped spaces are replaced with whitespace character classes to support
          multiline matching.
        - Logging is performed if verbosity is enabled in the object configuration.
        """
        words = []
        full_match = ArFlags.FULL_MATCH in self.flags

        def add_bounds(my_word):
            if re.match(r'\w', my_word[0]):
                my_word = rf"\b{my_word}"
            if re.match(r'\w', my_word[-1]):
                my_word = rf"{my_word}\b"
            return my_word

        if self.match_list is not None and isinstance(self.match_list, list):
            # full match done as whole word match per item in list when using list-match
            for word in self.match_list:
                if isinstance(word, list):
                    sub_list = []
                    for synonym in word:
                        synonym = re.escape(synonym)
                        if full_match:
                            # full_match with a list trigger means word boundaries are added
                            # e.g. if "word" is in the list, it will not match "words" or "sword"
                            synonym = add_bounds(synonym)
                        sub_list.append(synonym)
                    # synonyms. a list of words at this level indicates one word from a list must match
                    word = f"({'|'.join(sub_list)})"
                else:
                    word = re.escape(word)
                    if full_match:
                        word = add_bounds(word)
                words.append(word)
        elif full_match:
            # full_match with a string trigger means the entire message must match
            words = [rf"^{re.escape(self.ar_row.trigger)}$"]
        else:
            words = [str(re.escape(self.ar_row.trigger))]

        for i, word in enumerate(list(words)):
            # replace escaped spaces with whitespace character class for multiline matching
            words[i] = re.sub(r'\\ ', r'\\s+', word)

        if self.verbose:
            Logging.info(f"Match list for ar {self.id}: {words}")
        return words

    def get_raw_responses(self, response_type: AutoResponseType) -> list[AutoResponse]:
        try:
            raw_list = [x for x in self.responses[str(response_type)] if x.active]
            return raw_list
        except KeyError:
            Logging.info(f"invalid response type: {response_type}")
            raise

    def get_random_response(self, response_type: AutoResponseType) -> Optional[AutoResponse]:
        responses = self.get_raw_responses(response_type)
        if len(responses) > 0:
            return random.choice(responses)
        return None

    def short_description(self, wrapper: str = '`') -> str:
        """Formatted description for dialogs. Output limited to 30 characters

        Returns
        -------
        str
            Trigger string is returned if it's shorter than the output limit.
            If the trigger is longer than the output limit,returns the front and back of the trigger,
            joined with ellipsis
        """
        output_limit = 30
        ellipsis_str = ' ... '
        if (len(self.ar_row.trigger) + len(ellipsis_str)) > output_limit:
            part_a = self.ar_row.trigger[0:int(output_limit/2) - len(ellipsis_str)]
            part_b = self.ar_row.trigger[-int(output_limit/2) + len(ellipsis_str):]
            output = f"{wrapper}{part_a}{ellipsis_str}{part_b}{wrapper}"
            return re.sub(URL_MATCHER, r'<\1>', output)
        return re.sub(URL_MATCHER, r'<\1>', self.ar_row.trigger)

    def get_info(self):
        flags_desc = self.flags.get_flags_description()
        if self.chance < 1:
            flags_desc += f"\n{DISCORD_INDENT} Chance of response: {self.chance * 100}%"
        channel_data = [
            (self.response_channels, "Respond in"),
            (self.listen_channels, "Listen in"),
            (self.log_channels, "Log in"),
            (self.ignored_channels, "Ignore in"),
            (self.mod_channels, "Mod-Respond in"),
        ]
        for c, x in channel_data:
            if c:
                my_mentions = [f"<#{cid}>" for cid in c]
                my_mentions = ', '.join(my_mentions)
                flags_desc += f"\n{DISCORD_INDENT} {x}: {my_mentions}"
        return f"__**[{self.id}]**__ {self.short_description()}\n{flags_desc}"

    def flag_is_set(self, flag: ArFlags):
        return flag in self.flags

    # TODO: integrity check with rule enforcement that can't be met by db constraints. e.g.:
    #  only one response channel per autoresponder (constraint would work)
    #  if listen channels are set, disallow ignore channels?
    #  if ignore channels are set, disallow listen channels?
    #  or simply report when there is a conflict and defer to global ignore list

    # TODO: remove get_global_ignore_channels and replace by loading ignore channels into memory
    #  refreshing when updated, or periodically

    @staticmethod
    async def get_global_ignore_channels(bot, guild_id) -> tuple[list[AutoResponderChannel], list[TextChannel], list[int], str]:
        """
        Get a list of db rows representing AutoResponder global ignores for this guild,
        a list of corresponding channels, and a descriptive string that includes channel mentions

        Parameters
        ----------
        bot
        guild_id

        Returns
        -------
        tuple
            Db rows, Channels, Channel IDs, Description
        """
        # Channels are unique, but ARC has no guild field, so filter by guild.get_channel
        rows = await AutoResponderChannel.filter(
            autoresponder=None,
            type=AutoResponderChannelType.ignore)
        channels = []
        channel_ids = []
        filtered_rows = []
        for row in rows:
            my_channel = bot.get_guild(guild_id).get_channel(row.channelid)
            if my_channel:
                channels.append(my_channel)
                channel_ids.append(my_channel.id)
                filtered_rows.append(row)
        description = ', '.join([c.mention for c in channels]) if channels else "[NONE]"
        description = f"AutoResponder global ignore list in {bot.get_guild(guild_id).name}:\n{description}"
        return filtered_rows, channels, channel_ids, description

    @staticmethod
    async def fetch_rule(guild_id, autoresponder_id) -> 'ArRule':  # TODO: change return hint to typing.Self when py 3.11
        try:
            row = await AutoResponder.get(id=autoresponder_id, serverid=guild_id)
        except (MultipleObjectsReturned, DoesNotExist):
            await Utils.guild_log(guild_id, f"Failed to find autoresponder id {autoresponder_id}")
            raise
        return await ArRule.from_db_row(row)

    @staticmethod
    async def from_db_row(ar_row: AutoResponder) -> 'ArRule':  # TODO: change return hint to typing.Self when py 3.11
        """Load the rule from the database and parse the configuration

        Parameters
        ----------
        ar_row: AutoResponder

        Returns
        -------
        ArRule
        """

        # interpret flags bitmask and store for reference
        flags = ArFlags(ar_row.flags)

        await ar_row.fetch_related()

        if ArRule.verbose:
            ar_pydantic = pydantic_model_creator(AutoResponder)
            p = await ar_pydantic.from_tortoise_orm(ar_row)
            print("AR ROW:", p.model_dump_json(indent=4))

        pub_responses = []
        log_responses = []
        mod_responses = []
        to_try = [
            (pub_responses, AutoResponseType.public),
            (log_responses, AutoResponseType.log),
            (mod_responses, AutoResponseType.mod),
        ]

        # populate self.responses by type from related response rows
        for arr, ar_type in to_try:
            try:
                for r in await ar_row.responses:
                    if r.type == ar_type:
                        arr.append(r)
            except NoValuesFetched:
                pass

        responses = {
            str(AutoResponseType.public): pub_responses,
            str(AutoResponseType.log): log_responses,
            str(AutoResponseType.mod): mod_responses,
        }

        #########################################
        # TODO: remove when migration is complete
        #
        # use JSON object for random response
        try:
            response = json.loads(ar_row.response)
        except JSONDecodeError:
            try:
                # leading and trailing quotes are checked
                response = json.loads(ar_row.response[1:-1])
            except JSONDecodeError:
                # not json. do not raise exception, use string instead
                response = ar_row.response

        if isinstance(response, int):
            response = str(response)

        if not isinstance(response, list):
            response = [response] if response else []
        else:
            response = [str(r) for r in response if str(r)]

        migrated = False
        for phrase in response:
            if not phrase:
                continue
            try:
                await AutoResponse.create(autoresponder=ar_row, response=phrase, type=AutoResponseType.public)
                Logging.info(
                    f"migrate response phrase `{phrase}` "
                    f"for ar_id {ar_row.id} to response table", TCol.Green)
                migrated = True
            except (OperationalError, IntegrityError, TransactionManagementError):
                Logging.info(f"Failed to create response `{phrase}` for ar id {ar_row.id}", TCol.Fail)

        if migrated:
            # clear from autoresponder row
            ar_row.response = ''
            await ar_row.save()
            Logging.info(f"ar row {ar_row.id} updated", TCol.Green)
        #
        # TODO: remove when migration is complete
        #########################################

        # use JSON object to require each of several triggers in any order
        try:
            # TODO: enforce structure and depth limit. Currently written to accept 1D and 2D array of strings
            # TODO: convert trigger to table?
            match_list = json.loads(ar_row.trigger)
            if not isinstance(match_list, list):
                match_list = None

            # 1D Array means a matching string will have each word in the list, in any order
            # A list in any index of the list means any *one* word in the 2nd level list will match
            # e.g. ["one", ["two", "three"]] will match a string that has "one" AND ("two" OR "three")
            # "this is one of two example sentences that will match."
            # "there are three examples and this one will match as well."
            # "A sentence like this one will NOT match."
        except JSONDecodeError:
            # not json. do not raise exception
            match_list = None

        chance = ar_row.chance / 10000  # ar_row.chance is 0-10,000. make it look more like a percentage

        listen_channels = []
        response_channels = []
        log_channels = []
        ignored_channels = []
        mod_channels = []

        for c in await ar_row.channels:
            if c.type == AutoResponderChannelType.listen:
                listen_channels.append(c.channelid)
            elif c.type == AutoResponderChannelType.response:
                response_channels.append(c.channelid)
            elif c.type == AutoResponderChannelType.ignore:
                ignored_channels.append(c.channelid)
            elif c.type == AutoResponderChannelType.mod:
                mod_channels.append(c.channelid)

        #########################################
        # TODO: remove when migration is complete
        #
        if ar_row.listenchannelid:
            listen_channels.append(ar_row.listenchannelid)

        if ar_row.responsechannelid:
            response_channels.append(ar_row.responsechannelid)

        if ar_row.logchannelid:
            log_channels.append(ar_row.logchannelid)
        #
        # TODO: remove when migration is complete
        #########################################

        # TODO: remove response when migration is complete
        if response:
            Logging.info(f"add to responses: {response}")
            pub_responses += response

        if ArRule.verbose:
            Logging.info(f"""ARTD.from_db_row:
                id: {ar_row.id},
                match_list: {match_list},
                response: [],
                responses={responses},
                flags: {flags},
                chance: {chance},
                guild_id: {ar_row.serverid},
                listen_channels: {listen_channels},
                response_channels: {response_channels},
                log_channels: {log_channels},
                ignored_channels: {ignored_channels},
                mod_channels: {mod_channels},
                ar_row: {ar_row}
            """)

        return ArRule(
            id=ar_row.id,
            match_list=match_list,
            response=[],
            responses=responses,
            flags=flags,
            chance=chance,
            guild_id=ar_row.serverid,
            listen_channels=listen_channels,
            response_channels=response_channels,
            log_channels=log_channels,
            ignored_channels=ignored_channels,
            mod_channels=mod_channels,
            ar_row=ar_row
        )
