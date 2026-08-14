from __future__ import annotations
import csv
import inspect
import json
import math
import traceback
import typing
import uuid
from datetime import datetime, timezone
from enum import EnumMeta, Enum
from json import JSONDecodeError
from typing import (TYPE_CHECKING, Union, Collection, Dict, Optional,
                    OrderedDict, Pattern, Tuple, Match)
from zoneinfo import ZoneInfo

from utils import Database

import discord
import sentry_sdk
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import (Embed, Colour, ConnectionClosed, Guild,
                     NotFound, HTTPException, AllowedMentions, Message,
                     InteractionResponse, Interaction, Member, TextChannel, Thread, DMChannel, Role, PartialMessageable)
from discord.abc import PrivateChannel, GuildChannel
from discord.ext.commands import Context

from utils import Logging, Configuration
from utils.Constants import *
from utils.Logging import TCol

if TYPE_CHECKING:
    from _typeshed import SupportsWrite
    from sky import Skybot

BOT: "Skybot"
GUILD_CONFIGS: Dict[int, Database.Guild] = {}
known_invalid_users: list[int] = []
user_cache: OrderedDict = OrderedDict()


class MetaEnum(EnumMeta):
    def __contains__(cls, item):
        try:
            cls(item)
        except ValueError:
            return False
        return True


class BaseEnum(Enum, metaclass=MetaEnum):
    pass


def get_home_guild() -> Guild:
    """
    Fetches and returns the home guild specified by the configuration.

    This function retrieves the `guild_id` set in the configuration and fetches
    the corresponding guild object from the bot's available guilds. If no guild
    is found with the given `guild_id`, an exception is raised.

    Returns
    -------
    Guild
        The guild object corresponding to the configured `guild_id`.

    Raises
    ------
    ValueError
        If no guild is found with the specified `guild_id` in the bot's guilds.
    """
    home_id = Configuration.get_var("guild_id")
    guild = BOT.get_guild(home_id)
    if guild is None:
        raise ValueError(f"No guild with id {home_id} found")
    return guild


def get_prefix() -> str:
    return Configuration.get_var("bot_prefix")


def get_chanconf_description(bot: Skybot, guild_id: int) -> str:
    message = f"guild {guild_id}" + '\n'
    try:
        for name, cid in bot.config_channels[guild_id].items():
            message += f"**{name}**: <#{cid}>" + '\n'
    except KeyError:
        pass
    return message


async def fetch_last_message_by_channel(channel: TextChannel) -> Optional[Message]:
    try:
        messages = [message async for message in channel.history(limit=1)]
        return messages[0]
    except NotFound:
        return None


# Command checks
async def permission_official_mute(ctx: Union[Context, Interaction]) -> bool:
    if isinstance(ctx, Context):
        author = ctx.author
        pctx = ctx
    elif isinstance(ctx, Interaction):
        author = ctx.user
        pctx = await BOT.get_context(ctx)
    else:
        return False

    po = permission_official(author.id, 'mute_members')
    pmb = await permission_manage_bot(pctx)
    return po or pmb


async def permission_official_ban(ctx: Union[Context, Interaction]) -> bool:
    if isinstance(ctx, Context):
        author = ctx.author
        pctx = ctx
    elif isinstance(ctx, Interaction):
        author = ctx.user
        pctx = await BOT.get_context(ctx)
    else:
        return False

    pbm = permission_official(author.id, 'ban_members')
    pmb = await permission_manage_bot(pctx)
    return pbm or pmb


#####################################
# App command interaction checks
#####################################

def check_is_owner(interaction: Interaction) -> bool:
    """Check if the user is the bot owner."""
    is_owner = interaction.user.id == BOT.owner_id
    if not is_owner:
        Logging.warn(f"check_is_owner: {interaction.user.id} != {BOT.owner_id}")
    return is_owner

#####################################
# END App command interaction checks
#####################################


async def can_mod_official(ctx: Union[Context, Interaction]) -> bool:
    if isinstance(ctx, Context):
        pctx = ctx
    elif isinstance(ctx, Interaction):
        pctx = await BOT.get_context(ctx)
    else:
        return False
    return await permission_official_ban(pctx)


def permission_official(member_id: int, permission_name: str) -> bool:
    # ban permission on official server - sort of a hack to propagate perms
    # TODO: better permissions model
    try:
        official_guild = get_home_guild()
        official_member = official_guild.get_member(member_id)
        if official_member is None:
            return False
        return getattr(official_member.guild_permissions, permission_name)
    except ValueError:
        return False


async def can_mod_guild(ctx: Union[Context, Interaction]) -> bool:
    author = ctx.author if isinstance(ctx, Context) else ctx.user

    guild = get_home_guild()
    member = guild.get_member(author.id)
    if member is None:
        return False
    return (bool(member.guild_permissions.mute_members) or
            BOT is not None and
            await permission_manage_bot(ctx))


async def permission_manage_bot(ctx: Union[Context, Interaction]) -> bool:
    author = ctx.author if isinstance(ctx, Context) else ctx.user
    guild = ctx.guild
    cmd_name = ctx.command.name if ctx.command is not None else '[no command]'

    is_admin = await BOT.member_is_admin(author.id)
    if is_admin:
        Logging.info(f"{inspect.stack()[1].filename}:{inspect.stack()[1].function} - admin granted to {author.name} for {cmd_name}", TCol.Green)
        return True

    if guild is not None and isinstance(author, Member):
        """
        Logging.info(
            f"{inspect.stack()[1].filename}:{inspect.stack()[1].function}"
            f" - checking permission by role. User: {author.name} Command: {cmd_name}",
            TCol.Warning)
        """
        guild_row = await BOT.get_guild_db_config(guild.id)
        if guild_row is None:
            return False
        db_admin_roles = await guild_row.admin_roles.filter()  # Roles saved in the db for this guild
        db_admin_role_ids = [row.roleid for row in db_admin_roles]
        config_role_ids = Configuration.get_var("admin_roles", [])  # roles saved in the config
        admin_role_ids = db_admin_role_ids + config_role_ids
        admin_roles = id_list_to_roles(guild, admin_role_ids)

        for role in admin_roles:
            if role in author.roles:
                Logging.info(f"admin granted by {role.name} role to {author.name}", TCol.Green)
                return True
    return False


async def can_help(ctx: Context) -> bool:
    user = ctx.author
    if isinstance(user, Member):
        return bool(user.guild_permissions.mute_members) or (await permission_manage_bot(ctx))
    return False

async def get_guild_log_channel(guild_id: int) -> Optional[GuildChannel]:
    # TODO: per-cog override for logging channel?
    channel = await get_guild_config_channel(guild_id, 'log')
    if not channel or isinstance(channel, (Thread, PrivateChannel)):
        raise ValueError(f"No log channel for guild {guild_id}")
    return channel


async def get_guild_rules_channel(guild_id: int) -> Optional[GuildChannel]:
    return await get_guild_config_channel(guild_id, 'rules')


async def get_guild_maintenance_channel(guild_id: int) -> Optional[GuildChannel]:
    return await get_guild_config_channel(guild_id, 'maintenance')


async def get_guild_config_channel(guild_id: int, name: str) -> Optional[GuildChannel]:
    config = await BOT.get_guild_db_config(guild_id)
    if config:
        channel = BOT.get_channel(getattr(config, f'{name}channelid'))
        if not channel or isinstance(channel, (Thread, PrivateChannel)):
            raise ValueError(f"No {name} channel for guild {guild_id}")
        return channel
    return None


async def guild_log( guild_id: int, msg: Optional[str] = None, embed: Optional[Embed] = None) -> Optional[Message]:
    if not (msg or embed):
        # can't send anything if there's no message or embed, so return none
        return None

    channel = await get_guild_log_channel(guild_id)
    if channel and isinstance(channel, (TextChannel, Thread, DMChannel)):
        try:
            args: dict = {"allowed_mentions": AllowedMentions.none()}
            if embed:
                args["embed"] = embed
            sent = await channel.send(msg, **args)
            return sent
        except HTTPException:
            pass

    # No channel or send failed. Send notice in bot server:
    sent = await Logging.bot_log(f"server {guild_id} is misconfigured for logging. Failed message:"
                                 f"```{msg}```", embed=embed)
    return sent


def id_list_to_roles(guild: Guild, id_list: list[int]) -> set[Role]:
    """Convert a list of integer role IDs to a list of validated roles for the requested guild.

    Parameters
    ----------
    guild
    id_list

    Returns
    -------
    set[Role]
    """
    id_set = set(id_list)
    output = set()
    for role_id in id_set:
        my_role = guild.get_role(role_id)
        if my_role:
            output.add(my_role)
    return output


def get_channel_description(bot: Skybot, channel_id: int) -> str:
    channel = bot.get_channel(channel_id)
    if not channel or isinstance(channel, PrivateChannel):
        return f"**[Invalid Channel ID {channel_id}]**"
    return f"**{channel.name}** {channel.mention} ({channel.id})"


def extract_info(o) -> str:
    info = ""
    if hasattr(o, "__dict__"):
        info += str(o.__dict__)
    elif hasattr(o, "__slots__"):
        items = dict()
        for slot in o.__slots__:
            try:
                items[slot] = getattr(o, slot)
            except AttributeError:
                pass
        info += str(items)
    else:
        info += str(o) + " "
    return info


async def do_re_search(pattern: Union[Pattern, str], subject: str) -> Optional[Match]:
    """
    Regex search coro to allow running regex as a task and timeout for poorly formed patterns
    :param pattern:
    :param subject:
    :return:
    """
    # Logging.info(f"pattern is {pattern}")
    match = re.search(pattern, subject)
    return match


def get_embed_and_log_exception(
        exception_type: str,
        exception: Exception,
        message: Optional[Message] = None,
        ctx: Optional[Union[Context, Interaction]] = None,
        *args,
        **kwargs) -> Optional[Embed]:
    with sentry_sdk.isolation_scope() as scope:
        embed = Embed(colour=Colour(0xff0000), timestamp=datetime.now(timezone.utc))

        # something went wrong, and it might have been in on_command_error, make sure we log to the log file first
        lines = [
            "\n_____EXCEPTION CAUGHT, DUMPING ALL AVAILABLE INFO_____",
            f"Type: {exception_type}"
        ]

        arg_info = ""
        for arg in list(args):
            arg_info += extract_info(arg) + "\n"
        if arg_info == "":
            arg_info = "No arguments"

        kwarg_info = ""
        for name, arg in kwargs.items():
            kwarg_info += "{}: {}\n".format(name, extract_info(arg))
        if kwarg_info == "":
            kwarg_info = "No keyword arguments"

        lines.append("======================Exception=======================")
        lines.append(f"{str(exception)} ({type(exception)})")

        lines.append("=======================ARG INFO=======================")
        lines.append(arg_info)
        sentry_sdk.add_breadcrumb(category='arg info', message=arg_info, level='info')

        lines.append("======================KWARG INFO======================")
        lines.append(kwarg_info)
        sentry_sdk.add_breadcrumb(category='kwarg info', message=kwarg_info, level='info')

        lines.append("======================STACKTRACE======================")
        tb = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
        lines.append(tb)

        if message is None and ctx is not None and hasattr(ctx, "message"):
            message = ctx.message

        if message is not None and hasattr(message, "content"):
            lines.append("===================ORIGINAL MESSAGE===================")
            lines.append(message.content)
            if message.content is None or message.content == "":
                content = "<no content>"
            else:
                content = message.content
            scope.set_tag('message content', content)
            embed.add_field(name="Original message", value=trim_message(content, 1000), inline=False)

            lines.append("==============ORIGINAL MESSAGE (DETAILED)=============")
            lines.append(extract_info(message))

        if ctx is not None:
            lines.append("=====================COMMAND INFO=====================")

            if ctx.command is not None:
                lines.append(f"Command: {ctx.command.name}")
                embed.add_field(name="Command", value=ctx.command.name)
                scope.set_tag('command', ctx.command.name)

            if hasattr(ctx, "channel"):
                channel = ctx.channel
                channel_name = "Unknown Channel"
                if channel is not None:
                    if isinstance(channel, (Thread, PartialMessageable, DMChannel)):
                        name = f"channel {channel.id}"
                    else:
                        name = channel.name
                    channel_name = ('Private Message' if
                                    isinstance(channel, PrivateChannel) else
                                    f"{name} (`{channel.id}`)")
                lines.append(f"Channel: {channel_name}")
                embed.add_field(name="Channel", value=channel_name, inline=False)
                scope.set_tag('channel', channel_name)

            author = ctx.author if isinstance(ctx, Context) else ctx.user
            sender = f"{str(author)} (`{author.id}`)"
            scope.set_user({"id": author.id, "username": author.name})

            lines.append(f"Sender: {sender}")
            embed.add_field(name="Sender", value=sender, inline=False)

        lines.append(
            "__________________DATA DUMP COMPLETE__________________")
        Logging.error("\n".join(lines))

        for t in [ConnectionClosed, ClientOSError, ServerDisconnectedError]:
            if isinstance(exception, t):
                return None
        # nice embed for info on discord

        embed.set_author(name=exception_type)
        embed.add_field(name="Exception", value=f"{str(exception)} (`{type(exception)}`)", inline=False)
        if len(tb) < 1024:
            embed.add_field(name="Traceback", value=tb)
        else:
            embed.add_field(name="Traceback", value="stacktrace too long, see logs")
        sentry_sdk.capture_exception(exception)
        return embed


async def handle_exception(
        exception_type: str,
        exception: Exception,
        message: Optional[Message]=None,
        ctx: Optional[Union[Context, Interaction]]=None,
        *args,
        **kwargs) -> None:
    embed = get_embed_and_log_exception(exception_type, exception, message, ctx, *args, **kwargs)
    if embed and embed.fields:
        try:
            await Logging.bot_log(embed=embed)
        except Exception as ex:
            Logging.error(
                f"Failed to log to botlog, either Discord broke or something is seriously wrong!\n{ex}")
            Logging.error(traceback.format_exc())


def trim_message(message: str, limit: int) -> str:
    if len(message) < limit - 3:
        return message
    return f"{message[:limit - 3]}..."


async def get_user(uid: int, fetch: bool=True) -> Optional[discord.User]:
    user = BOT.get_user(uid)
    if user is None:
        if uid in known_invalid_users:
            return None
        if uid in user_cache:
            return user_cache[uid]
        if fetch:
            try:
                user = await BOT.fetch_user(uid)
                if len(user_cache) >= 10:  # Limit the cache size to the most recent 10
                    user_cache.popitem()
                user_cache[uid] = user
            except NotFound:
                known_invalid_users.append(uid)
                return None
    return user


def clean_user(user: Optional[discord.User]) -> str:
    if user is None:
        return "UNKNOWN USER"
    return f"{escape_markdown(user.name)}#{user.discriminator}"


async def username(uid: int, fetch: bool = True, do_clean: bool = True) -> str:
    user = await get_user(uid, fetch)
    if user is None:
        return "UNKNOWN USER"
    if do_clean:
        return clean_user(user)
    else:
        return f"{user.name}#{user.discriminator}"


def get_member_log_name(member: Optional[Union[discord.User, discord.Member]]) -> str:
    if member:
        return f"{member.mention} {member.display_name} ({member.id})"
    return "unknown user"


async def clean(
        text,
        guild: Optional[Guild] = None,
        markdown: Optional[bool] = True,
        links: Optional[bool] = True,
        emoji: Optional[bool] = True) -> str:
    text = str(text)
    if guild is not None:
        # resolve user mentions
        for uid in set(ID_MATCHER.findall(text)):
            name = "@" + await username(int(uid), False, False)
            text = text.replace(f"<@{uid}>", name)
            text = text.replace(f"<@!{uid}>", name)

        # resolve role mentions
        for uid in set(ROLE_ID_MATCHER.findall(text)):
            role = discord.utils.get(guild.roles, id=int(uid))
            if role is None or not isinstance(role, discord.Role):
                name = "@UNKNOWN ROLE"
            else:
                name = "@" + role.name
            text = text.replace(f"<@&{uid}>", name)

        # resolve channel names
        for uid in set(CHANNEL_ID_MATCHER.findall(text)):
            channel = guild.get_channel(int(uid))
            if channel is None:
                name = "#UNKNOWN CHANNEL"
            else:
                name = "#" + channel.name
            text = text.replace(f"<#{uid}>", name)

        # re-assemble emoji so such a way that they don't turn into twermoji

    urls = set(URL_MATCHER.findall(text))

    if markdown:
        text = escape_markdown(text)
    else:
        # Break up markdown and mentions with zero-width spaces
        text = text.replace("@", "@\u200B")
        # noinspection InvisibleCharacter
        text = text.replace("**", "*\u200B*")
        # noinspection InvisibleCharacter
        text = text.replace("``", "`\u200B`")

    if emoji:
        for e in set(EMOJI_MATCHER.findall(text)):
            a, b, c = zip(e)
            text = text.replace(f"<{a[0]}:{b[0]}:{c[0]}>", f"<{a[0]}\\:{b[0]}\\:{c[0]}>")

    if links:
        # find urls last so the < escaping doesn't break it
        for url in urls:
            text = text.replace(escape_markdown(url), f"<{url}>")

    return text


def escape_markdown(text: str) -> str:
    text = str(text)
    for c in ["\\", "`", "*", "_", "~", "|", "{", ">"]:
        text = text.replace(c, f"\\{c}")
    return text.replace("@", "@\u200b")


def fetch_from_disk(
        filename: str,
        alternative: Optional[str] = None) -> Union[None, dict, list, str, int, float]:
    try:
        with open(f"{filename}.json", encoding="UTF-8") as file:
            return json.load(file)
    except FileNotFoundError:
        if alternative is not None:
            return fetch_from_disk(alternative)
    except JSONDecodeError:
        if alternative is not None:
            return fetch_from_disk(alternative)
    return dict()


def save_to_disk(
        filename: str,
        data: Union[Tuple, Dict],
        ext: str="json",
        fields: Optional[Collection]=None) -> None:
    with open(f"{filename}.{ext}", "w", encoding="UTF-8", newline='') as file:
        do_save(file, data, ext, fields)


def save_to_buffer(
        buffer: SupportsWrite[str],
        data: Union[Tuple, Dict],
        ext: str="json",
        fields: Optional[Collection]=None) -> None:
    do_save(buffer, data, ext, fields)


def do_save(
        buffer: SupportsWrite[str],
        data: Union[Tuple, Dict],
        ext: str="json",
        fields: Optional[Collection]=None) -> None:
    if ext == 'json':
        json.dump(data, buffer, indent=4, skipkeys=True, sort_keys=True)
    elif ext == 'csv':
        if fields is None:
            raise ValueError("fields must be provided for CSV export")
        csvwriter = csv.DictWriter(buffer, fieldnames=fields)
        csvwriter.writeheader()
        for row in data:
            csvwriter.writerow(row)


def to_pretty_time(seconds: Union[int, float]) -> str:
    part_count = 0
    parts = {
        'week': 60 * 60 * 24 * 7,
        'day': 60 * 60 * 24,
        'hour': 60 * 60,
        'minute': 60,
        'second': 1
    }
    duration = ""

    for k, v in parts.items():
        if seconds / v >= 1:
            amount = math.floor(seconds / v)
            seconds -= amount * v
            if part_count == 1:
                duration += ", "
            duration += " " + f"{amount} {k}{'' if amount == 1 else 's'}"
        if seconds == 0:
            break
    return duration.strip()


def chunk_list_or_string(input_list, chunk_size: int):
    """
    cut input into chunks, maximum size is `chunk_size` and return a generator that goes through every chunk.
    chunks are contiguous and only the last one may have length less than `chunk_size`
    """
    for i in range(0, len(input_list), chunk_size):
        yield input_list[i:i + chunk_size]


def paginate(
        input_data: str,
        max_lines: int = 20,
        max_chars: int = 1900,
        prefix: str = "",
        suffix: str = "") -> list[str]:
    """
    splits the given text input into a list of pages to fit in Discord messages.

    Each page has provided prefix and suffix in it and is at most `max_chars` length, disregarding any leading and trailing whitespace.
    len(page) in code may be longer because of trailing whitespace, which Discord removes

    Parameters
    -----
    input_data : str
            string of arbitrary length
    max_lines : int
    max_chars : int
        max number of characters per page. one page is meant to fit in one message, so should be a positive integer
        less than the Discord message length a bot can send (2k characters right now).
        recommend setting lower than max to leave some buffer for other additions
    prefix: str
    suffix: str

    Returns
    -------
    a list of 0 or more non-empty strings
    """
    max_chars -= len(prefix) + len(suffix)
    #max_chars is now max number of characters we can read from input that would fit in one page
    lines = str(input_data).splitlines(keepends=True)
    pages = []
    page = ""
    count = 0

    def add_page(content):
        """
        adds on prefix and suffix to the given content and adds it as a page to the list.
        length of `content` must be less that `max_chars`.
        moves onto the next page by setting page to empty string
        """
        nonlocal pages, page
        pages.append(f"{prefix}{content}{suffix}")
        page = ""

    # try to split pages on lines first
    for line in lines:
        if len(page) + len(line) > max_chars or count == max_lines:
            # adding next line too long for this page, split by words
            words = line.split(" ")
            for word in words:
                if len(page) + len(word) > max_chars:
                    # adding next word is too long for this page.
                    # want to reduce number of mid-word splits so just save this page and start new one for next word
                    if page:
                        add_page(page)
                        count += 1
                    # if page would be too long and if word longer than max, split on char,
                    # else we start next page: page = word
                    if len(word) > max_chars:
                        for chunk in chunk_list_or_string(word, max_chars):
                            page = f"{chunk} "
                            if len(chunk) == max_chars:
                                add_page(page)
                            # last chunk might not fill page, nothing to do in that case
                    else:
                        page = f"{word} "
                else:
                    page += f"{word} "
        else:
            page += line
    # potential last page. only if it has content
    if page:
        add_page(page)
    return pages


def pages_to_embed(
        content: str,
        embed: discord.Embed,
        field_name: str = "Contents") -> None:
    contents = paginate(content, max_chars=900)
    i = 0
    for chunk in contents:
        i = i + 1
        embed.add_field(
            name=f"{field_name}{', part ' + str(i) if len(contents) > 1 else ''}",
            value=f"```{chunk}```",
            inline=False)


def get_new_uuid_str() -> str:
    return str(uuid.uuid4())


def closest_power2_log(num: int) -> int:
    lower = int(math.floor(math.log2(num)))
    upper = int(math.ceil(math.log2(num)))
    lower_pow = 1 << lower
    upper_pow = 1 << upper
    if num < (lower_pow + upper_pow)/2:
        return lower_pow
    return upper_pow


def closest_power2_str(num: int) -> int:
    # faster in small runs, slower overall
    upper_exp = len(f"{num:b}")
    lower_exp = upper_exp - 1
    upper_pow = 1 << upper_exp
    lower_pow = 1 << lower_exp
    # use midpoint to decide which
    if num < (lower_pow + upper_pow)/2:
        return lower_pow
    return upper_pow


def is_power_of_two(num: int) -> bool:
    if num < 0:
        return False
    return bool(num and (not(num & (num - 1))))


def get_bitshift(value: int) -> int:
    """Get the bit position for a power of two value. If a non-power-2 number is input, return value is False

    Parameters
    ----------
    value: int
        Input number

    Returns
    -------
    int Bit-shift of the input value
    """
    if is_power_of_two(value):
        # power of two guarantees positive and only one bit is set

        # Equivalent to final implementation:
        # bin_value = bin(value).lstrip('-0b')
        # return len(bin_value) - 1

        # Equivalent to obscure implementation:
        # bin_value = bin(value).lstrip('-0b')
        # bin_reversed = bin_value[::-1]
        # bit_position = bin_reversed.index('1')
        # return bit_position

        # Obscure:
        # return [int(c) for i, c in enumerate(bin(value)[:1:-1])].index(1)

        return int.bit_length(value)-1
    raise ValueError


def interaction_response(interaction: Interaction) -> InteractionResponse:
    """This exists only for type hinting because pycharm can't properly infer type for interaction.response"""
    return typing.cast(InteractionResponse, interaction.response)

def parse_date_with_pacific_fallback(date_str: str) -> datetime:
    """Parses a 'YYYY-MM-DD HH:MM' string.

    Allows a trailing offset after a space.
    Falls back to America/Los_Angeles if the offset is missing.
    """
    # Clean up double spaces and strip trailing whitespace
    cleaned = re.sub(r"\s+", " ", date_str.strip())

    # Regular expression to detect a trailing offset: +/-HH:MM, +/-HHMM, +/-HH, or Z
    offset_pattern = r"(Z|[+-]\d{2}(:?\d{2})?)$"

    if re.search(offset_pattern, cleaned):
        # 1. Offset exists. Replace the first space with 'T' to make it strict ISO 8601
        # Example conversion: "2026-07-29 19:55 -07:00" -> "2026-07-29T19:55-07:00"
        iso_str = cleaned.replace(" ", "T", 1).replace(" T", "T")
        return datetime.fromisoformat(iso_str)
    else:
        # 2. Offset is missing. Parse as naive datetime, then attach Pacific Time
        # We append ":00" to ensure compatibility with older Python 3.7-3.10 versions
        naive_dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:00")
        return naive_dt.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
