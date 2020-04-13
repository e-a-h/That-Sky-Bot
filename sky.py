import asyncio
import signal

import sentry_sdk
from discord.ext import commands
from discord.ext.commands import Bot
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import ConnectionClosed, Embed, Colour
from prometheus_client import CollectorRegistry
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

from utils import Logging, Configuration, Utils, Emoji, Database

from utils.PrometheusMon import PrometheusMon

class Skybot(Bot):
    loaded = False
    metrics_reg = CollectorRegistry()

    def __init__(self, *args, loop=None, **kwargs):
        super().__init__(*args, loop=loop, **kwargs)
        self.shutting_down = False
        self.metrics = PrometheusMon(self)
        self.config_channels = dict()
        self.db_keepalive = None

    async def on_ready(self):
        if not self.loaded:
            Logging.BOT_LOG_CHANNEL = self.get_channel(Configuration.get_var("log_channel"))
            Emoji.initialize(self)

            for cog in Configuration.get_var("cogs"):
                try:
                    self.load_extension("cogs." + cog)
                except Exception as e:
                    await Utils.handle_exception(f"Failed to load cog {cog}", self, e)
            Logging.info("Cogs loaded")
            self.db_keepalive = self.loop.create_task(self.keepDBalive())
            self.loaded = True

        await Logging.bot_log("Sky bot soaring through the skies!")

    def get_config_channel(self, guild_id: int, channel_name: str):
        if Utils.validate_channel_name(channel_name):
            try:
                this_channel_id = self.config_channels[guild_id][channel_name]
                # TODO: catch keyerror and log in guild that channel is not configured
                return self.get_channel(this_channel_id)
            except Exception as ex:
                pass
        return None

    async def close(self):
        Logging.info("Shutting down?")
        if not self.shutting_down:
            Logging.info("Shutting down...")
            self.shutting_down = True
            await Logging.bot_log(f"Skybot shutting down!")
            self.db_keepalive.cancel()
            temp = []
            for cog in self.cogs:
                temp.append(cog)
            for cog in temp:
                Logging.info(f"unloading cog {cog}")
                c = self.get_cog(cog)
                if hasattr(c, "shutdown"):
                    await c.shutdown()
                self.unload_extension(f"cogs.{cog}")
        return await super().close()

    async def on_command_error(bot, ctx: commands.Context, error):
        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(error)
        elif isinstance(error, commands.CheckFailure):
            pass
        elif isinstance(error, commands.CommandOnCooldown):
            if ctx.command.name in ['krill']:
                # commands in this list have custom cooldown handler
                return
            await ctx.send(error)
        elif isinstance(error, commands.MissingRequiredArgument):
            param = list(ctx.command.params.values())[min(len(ctx.args) + len(ctx.kwargs), len(ctx.command.params))]
            bot.help_command.context = ctx
            await ctx.send(
                f"{Emoji.get_chat_emoji('NO')} You are missing a required command argument: `{param._name}`\n{Emoji.get_chat_emoji('WRENCH')} Command usage: `{bot.help_command.get_command_signature(ctx.command)}`")
        elif isinstance(error, commands.BadArgument):
            param = list(ctx.command.params.values())[min(len(ctx.args) + len(ctx.kwargs), len(ctx.command.params))]
            bot.help_command.context = ctx
            await ctx.send(
                f"{Emoji.get_chat_emoji('NO')} Failed to parse the ``{param._name}`` param: ``{error}``\n{Emoji.get_chat_emoji('WRENCH')} Command usage: `{bot.help_command.get_command_signature(ctx.command)}`")
        elif isinstance(error, commands.CommandNotFound):
            return

        else:
            await Utils.handle_exception("Command execution failed", bot,
                                         error.original if hasattr(error, "original") else error, ctx=ctx)
            # notify caller
            e = Emoji.get_chat_emoji('BUG')
            if ctx.channel.permissions_for(ctx.me).send_messages:
                await ctx.send(f"{e} Something went wrong while executing that command {e}")

    async def keepDBalive(self):
        while not self.is_closed():
            Database.connection.connection().ping(True)
            await asyncio.sleep(3600)


def before_send(event, hint):
    if event['level'] == "error" and 'logger' in event.keys() and event['logger'] == 'gearbot':
        return None  # we send errors manually, in a much cleaner way
    if 'exc_info' in hint:
        exc_type, exc_value, tb = hint['exc_info']
        for t in [ConnectionClosed, ClientOSError, ServerDisconnectedError]:
            if isinstance(exc_value, t):
                return
    return event


if __name__ == '__main__':
    Logging.init()
    Logging.info("Launching thatskybot!")

    dsn = Configuration.get_var('SENTRY_DSN', '')
    dsn_env = Configuration.get_var('SENTRY_ENV', 'Dev')
    if dsn != '':
        sentry_sdk.init(dsn, before_send=before_send, environment=dsn_env, integrations=[AioHttpIntegration()])

    Database.init()

    loop = asyncio.get_event_loop()

    skybot = Skybot(command_prefix=Configuration.get_var("bot_prefix"), case_insensitive=True, loop=loop)
    skybot.remove_command("help")

    Utils.BOT = skybot

    try:
        for signame in ('SIGINT', 'SIGTERM'):
           loop.add_signal_handler(getattr(signal, signame), lambda: asyncio.ensure_future(skybot.close()))
    except NotImplementedError:
        pass

    try:
        loop.run_until_complete(skybot.start(Configuration.get_var("token")))
    except KeyboardInterrupt:
        pass
    finally:
        if not skybot.is_closed():
            loop.run_until_complete(skybot.close())
        loop.close()

    Logging.info("Shutdown complete")
