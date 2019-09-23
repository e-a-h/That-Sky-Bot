import csv
import json
import math
import re
import time
import traceback
from collections import OrderedDict, namedtuple
from datetime import datetime
from json import JSONDecodeError

import discord
import sentry_sdk
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import Embed, Colour, ConnectionClosed, NotFound
from discord.abc import PrivateChannel

from utils import Logging, Configuration

BOT = None
ID_MATCHER = re.compile("<@!?([0-9]+)>")
ROLE_ID_MATCHER = re.compile("<@&([0-9]+)>")
CHANNEL_ID_MATCHER = re.compile("<#([0-9]+)>")
MENTION_MATCHER = re.compile("<@[!&]?\\d+>")
URL_MATCHER = re.compile(r'((?:https?://)[a-z0-9]+(?:[-._][a-z0-9]+)*\.[a-z]{2,5}(?::[0-9]{1,5})?(?:/[^ \n<>]*)?)',
                         re.IGNORECASE)
EMOJI_MATCHER = re.compile('<(a?):([^: \n]+):([0-9]+)>')
NUMBER_MATCHER = re.compile(r"\d+")


def extract_info(o):
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


async def handle_exception(exception_type, bot, exception, event=None, message=None, ctx=None, *args, **kwargs):
    with sentry_sdk.push_scope() as scope:
        embed = Embed(colour=Colour(0xff0000), timestamp=datetime.utcfromtimestamp(time.time()))

        # something went wrong and it might have been in on_command_error, make sure we log to the log file first
        lines = [
            "\n===========================================EXCEPTION CAUGHT, DUMPING ALL AVAILABLE INFO===========================================",
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

        lines.append("======================Exception======================")
        lines.append(f"{str(exception)} ({type(exception)})")

        lines.append("======================ARG INFO======================")
        lines.append(arg_info)
        sentry_sdk.add_breadcrumb(category='arg info', message=arg_info, level='info')

        lines.append("======================KWARG INFO======================")
        lines.append(kwarg_info)
        sentry_sdk.add_breadcrumb(category='kwarg info', message=kwarg_info, level='info')

        lines.append("======================STACKTRACE======================")
        tb = "".join(traceback.format_tb(exception.__traceback__))
        lines.append(tb)

        if message is None and event is not None and hasattr(event, "message"):
            message = event.message

        if message is None and ctx is not None:
            message = ctx.message

        if message is not None and hasattr(message, "content"):
            lines.append("======================ORIGINAL MESSAGE======================")
            lines.append(message.content)
            if message.content is None or message.content == "":
                content = "<no content>"
            else:
                content = message.content
            scope.set_tag('message content', content)
            embed.add_field(name="Original message", value=trim_message(content, 1000), inline=False)

            lines.append("======================ORIGINAL MESSAGE (DETAILED)======================")
            lines.append(extract_info(message))

        if event is not None:
            lines.append("======================EVENT NAME======================")
            lines.append(event)
            scope.set_tag('event name', event)
            embed.add_field(name="Event", value=event)

        if ctx is not None:
            lines.append("======================COMMAND INFO======================")

            lines.append(f"Command: {ctx.command.name}")
            embed.add_field(name="Command", value=ctx.command.name)
            scope.set_tag('command', ctx.command.name)

            channel_name = 'Private Message' if isinstance(ctx.channel,
                                                           PrivateChannel) else f"{ctx.channel.name} (`{ctx.channel.id}`)"
            lines.append(f"Channel: {channel_name}")
            embed.add_field(name="Channel", value=channel_name, inline=False)
            scope.set_tag('channel', channel_name)

            sender = f"{str(ctx.author)} (`{ctx.author.id}`)"
            scope.user = dict(id=ctx.author.id, username=str(ctx.author))
            lines.append(f"Sender: {sender}")
            embed.add_field(name="Sender", value=sender, inline=False)

        lines.append(
            "===========================================DATA DUMP COMPLETE===========================================")
        Logging.error("\n".join(lines))

        for t in [ConnectionClosed, ClientOSError, ServerDisconnectedError]:
            if isinstance(exception, t):
                return
        # nice embed for info on discord

        embed.set_author(name=exception_type)
        embed.add_field(name="Exception", value=f"{str(exception)} (`{type(exception)}`)", inline=False)
        if len(tb) < 1024:
            embed.add_field(name="Traceback", value=tb)
        else:
            embed.add_field(name="Traceback", value="stacktrace too long, see logs")
        sentry_sdk.capture_exception(exception)
    try:
        await Logging.bot_log(embed=embed)
    except Exception as ex:
        Logging.error(
            f"Failed to log to botlog, either Discord broke or something is seriously wrong!\n{ex}")
        Logging.error(traceback.format_exc())


def trim_message(message, limit):
    if len(message) < limit - 3:
        return message
    return f"{message[:limit - 3]}..."


known_invalid_users = []
user_cache = OrderedDict()


def is_admin(user):
    for role in user.roles:
        if role.id in Configuration.get_var('admin_roles'):
            return True
    return False

async def get_user(uid, fetch=True):
    UserClass = namedtuple("UserClass", "name id discriminator bot avatar_url created_at is_avatar_animated mention")
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


def clean_user(user):
    if user is None:
        return "UNKNOWN USER"
    return f"{escape_markdown(user.name)}#{user.discriminator}"


async def username(uid, fetch=True, clean=True):
    user = await get_user(uid, fetch)
    if user is None:
        return "UNKNOWN USER"
    if clean:
        return clean_user(user)
    else:
        return f"{user.name}#{user.discriminator}"


async def clean(text, guild=None, markdown=True, links=True, emoji=True):
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
            if role is None:
                name = "@UNKNOWN ROLE"
            else:
                name = "@" + role.name
            text = text.replace(f"<@&{uid}>", name)

        # resolve channel names
        for uid in set(CHANNEL_ID_MATCHER.findall(text)):
            channel = guild.get_channel(uid)
            if channel is None:
                name = "#UNKNOWN CHANNEL"
            else:
                name = "#" + channel.name
            text = text.replace(f"<@#{uid}>", name)

        # re-assemble emoji so such a way that they don't turn into twermoji

    urls = set(URL_MATCHER.findall(text))

    if markdown:
        text = escape_markdown(text)
    else:
        text = text.replace("@", "@\u200b").replace("**", "*​*").replace("``", "`​`")

    if emoji:
        for e in set(EMOJI_MATCHER.findall(text)):
            a, b, c = zip(e)
            text = text.replace(f"<{a[0]}:{b[0]}:{c[0]}>", f"<{a[0]}\\:{b[0]}\\:{c[0]}>")

    if links:
        # find urls last so the < escaping doesn't break it
        for url in urls:
            text = text.replace(escape_markdown(url), f"<{url}>")

    return text


def escape_markdown(text):
    text = str(text)
    for c in ["\\", "`", "*", "_", "~", "|", "{", ">"]:
        text = text.replace(c, f"\\{c}")
    return text.replace("@", "@\u200b")


def fetch_from_disk(filename, alternative=None):
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


def save_to_disk(filename, data, ext="json", fields=None):
    with open(f"{filename}.{ext}", "w", encoding="UTF-8", newline='') as file:
        if ext == 'json':
            json.dump(data, file, indent=4, skipkeys=True, sort_keys=True)
        elif ext == 'csv':
            csvwriter = csv.DictWriter(file, fieldnames=fields)
            csvwriter.writeheader()
            for row in data:
                csvwriter.writerow(row)


def to_pretty_time(seconds):
    partcount = 0
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
            if partcount == 1:
                duration += ", "
            duration += " " + f"{amount} {k}{'' if amount is 1 else 's'}"
        if seconds == 0:
            break
    return duration.strip()
