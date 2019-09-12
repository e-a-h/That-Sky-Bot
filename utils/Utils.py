import time
import traceback
from datetime import datetime

import sentry_sdk
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import Embed, Colour, ConnectionClosed
from discord.abc import PrivateChannel

from utils import Logging


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
