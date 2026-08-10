import functools
import logging
import os
import sys
import traceback
import typing
from enum import Enum
from logging.handlers import TimedRotatingFileHandler
from typing import Literal, get_args

from discord import TextChannel, Embed

BOT_LOG_CHANNEL: typing.Union[TextChannel, None] = None

LOGGER = logging.getLogger('thatskybot')  # logs from this bot
DISCORD_LOGGER = logging.getLogger('discord')  # logs from discord.py

LogLevelOptions = Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
LOG_LEVELS = get_args(LogLevelOptions)

class TCol(Enum):
    Header = '\033[95m'
    Blue = '\033[94m'
    Cyan = '\033[96m'
    Green = '\033[92m'
    Warning = '\033[93m'
    Fail = '\033[91m'
    End = '\033[0m'
    Bold = '\033[1m'
    Underline = '\033[4m'


class RateLimitStackFilter(logging.Filter):
    """Attach the awaiting coroutine stack to discord.py's 429 warnings.

    discord.py logs the rate limited route but not the caller. Coroutine frames
    stay on the stack while awaiting, so the stack captured here names the cog
    or task loop that issued the request. Formatter.format() appends
    record.stack_info on its own, so no format string change is needed.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING and "being rate limited" in record.getMessage():
            record.stack_info = "".join(traceback.format_stack())
        return True


def init():
    LOGGER.setLevel(logging.INFO)
    DISCORD_LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    DISCORD_LOGGER.addHandler(handler)

    if not os.path.isdir("logs"):
        os.mkdir("logs")
    handler = TimedRotatingFileHandler(
        filename='logs/thatskybot.log',
        encoding='utf-8',
        when="midnight",
        backupCount=30)
    handler.setFormatter(formatter)
    DISCORD_LOGGER.addHandler(handler)
    LOGGER.addHandler(handler)

    # discord.py logs 429s from discord.http; the filter adds the calling stack
    logging.getLogger('discord.http').addFilter(RateLimitStackFilter())


async def bot_log(message: typing.Optional[str]=None, embed: typing.Optional[Embed]=None):
    if BOT_LOG_CHANNEL is not None:
        if embed:
            return await BOT_LOG_CHANNEL.send(content=message, embed=embed)
        else:
            return await BOT_LOG_CHANNEL.send(message)
    return None


def log_format(subject:str, *styles:TCol)->str:
    output = subject
    for style in styles:
        output = f"{style.value}{output}{TCol.End.value}"
    return output


def color_log(log_func):
    @functools.wraps(log_func)
    def color_wrapper(message:str, *styles:TCol, **kwargs):
        log_func(log_format(message, *styles), **kwargs)
    return color_wrapper


@color_log
def debug(message, *style, **kwargs):
    LOGGER.debug(message, **kwargs)


@color_log
def info(message, *style, **kwargs):
    LOGGER.info(message, **kwargs)


@color_log
def warn(message, *style, **kwargs):
    LOGGER.warning(message, **kwargs)


@color_log
def error(message, *style, **kwargs):
    LOGGER.error(message, **kwargs)


def log_always(message, *styles: TCol, level: int = logging.INFO, logger: logging.Logger = LOGGER):
    """Emit one record regardless of the logger's current level.

    Bypasses the level threshold (Logger.handle skips isEnabledFor) so audit
    lines like "log level changed" always appear, without mutating global state.
    """
    formatted = log_format(message, *styles)
    if logger.isEnabledFor(level):
        logger.log(level, formatted)
    else:
        record = logger.makeRecord(logger.name, level, "(unknown)", 0, formatted, (), None)
        logger.handle(record)


def set_level(level:LogLevelOptions, logger: logging.Logger = LOGGER):
    if level not in LOG_LEVELS:
        raise ValueError(f"Invalid log level: {level}")
    log_always(f"{logger}: Setting log level to {level}", TCol.Underline, TCol.Cyan)
    logger.setLevel(level)
    if logger == LOGGER:
        debug(f"DEBUG", TCol.Green)
        info(f"INFO", TCol.Cyan)
        warn(f"WARN", TCol.Warning)
        error(f"ERROR", TCol.Fail)


def get_level(logger) -> int:
    return logger.getEffectiveLevel()
