import asyncio
import glob
import importlib
import os
import re
import signal
import sys

import sentry_sdk
from discord.ext import commands
from discord.ext.commands import Bot
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import ConnectionClosed, Intents
from prometheus_client import CollectorRegistry
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

from utils import Logging, Configuration, Utils, Emoji, Database
from utils.Database import BotAdmin
from utils.PrometheusMon import PrometheusMon


class Skybot(Bot):
    loaded = False
    metrics_reg = CollectorRegistry()
    data = dict()

    def __init__(self, *args, loop=None, **kwargs):
        super().__init__(*args, loop=loop, **kwargs)
        self.shutting_down = False
        self.metrics = PrometheusMon(self)
        self.config_channels = dict()
        self.db_keepalive = None
        sys.path.append(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "sky-python-music-sheet-maker",
                         "python"))

    async def on_ready(self):
        if self.loaded:
            Logging.info("Skybot reconnect")
            return

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

        await Logging.bot_log("Skybot soaring through the skies!")

    def get_guild_log_channel(self, guild_id):
        return self.get_guild_config_channel(guild_id, 'log')

    def get_guild_rules_channel(self, guild_id):
        return self.get_guild_config_channel(guild_id, 'rules')

    def get_guild_welcome_channel(self, guild_id):
        return self.get_guild_config_channel(guild_id, 'welcome')

    def get_guild_entry_channel(self, guild_id):
        return self.get_guild_config_channel(guild_id, 'entry')

    def get_guild_maintenance_channel(self, guild_id):
        return self.get_guild_config_channel(guild_id, 'maintenance')

    def get_guild_config_channel(self, guild_id, name):
        config = self.get_config(guild_id)
        if config:
            return self.get_channel(getattr(config, f'{name}channelid'))
        return None

    def get_config(self, guild_id):
        try:
            return self.get_cog('GuildConfig').get_config(guild_id)
        except Exception as e:
            Utils.get_embed_and_log_exception("--------Failed to get config--------", self, e)
            return None

    def get_config_channel(self, guild_id: int, channel_name: str):
        # TODO: replace usage with get_guild_*_channel above
        if Utils.validate_channel_name(channel_name):
            try:
                this_channel_id = self.config_channels[guild_id][channel_name]
                # TODO: catch keyerror and log in guild that channel is not configured
                return self.get_channel(this_channel_id)
            except Exception as ex:
                pass
        return None

    async def permission_manage_bot(self, ctx):
        db_admin = BotAdmin.get_or_none(userid=ctx.author.id) is not None
        # Logging.info(f"db_admin: {'yes' if db_admin else 'no'}")
        owner = await ctx.bot.is_owner(ctx.author)
        # Logging.info(f"owner: {'yes' if owner else 'no'}")
        in_admins = ctx.author.id in Configuration.get_var("ADMINS", [])
        # Logging.info(f"in_admins: {'yes' if in_admins else 'no'}")
        has_admin_role = False
        if ctx.guild:
            for role in ctx.author.roles:
                if role in Configuration.get_var("admin_roles", []):
                    has_admin_role = True
        # Logging.info(f"has_admin_role: {'yes' if has_admin_role else 'no'}")
        return db_admin or owner or in_admins or has_admin_role

    async def guild_log(self, guild_id: int, message=None, embed=None):
        channel = self.get_guild_log_channel(guild_id)
        if channel and (message or embed):
            return await channel.send(content=message, embed=embed)

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
        elif isinstance(error, commands.MaxConcurrencyReached):
            await ctx.send(f"Too many people are using the `{ctx.invoked_with}` command right now. Try again later")
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
        elif isinstance(error, commands.UnexpectedQuoteError):
            bot.help_command.context = ctx
            await ctx.send(
                f"{Emoji.get_chat_emoji('NO')} There are quotes in there that I don't like\n{Emoji.get_chat_emoji('WRENCH')} Command usage: `{bot.help_command.get_command_signature(ctx.command)}`")
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


def run_db_migrations():
    dbv = int(Configuration.get_persistent_var('db_version', 0))
    Logging.info(f"db version is {dbv}")
    dbv_list = [f for f in glob.glob("db_migrations/db_migrate_*.py")]
    dbv_pattern = re.compile(r'db_migrations/db_migrate_(\d+)\.py', re.IGNORECASE)
    migration_count = 0
    for filename in sorted(dbv_list):
        # get the int version number from filename
        version = int(re.match(dbv_pattern, filename)[1])
        if version > dbv:
            try:
                Logging.info(f"--- running db migration version number {version}")
                spec = importlib.util.spec_from_file_location(f"migrator_{version}", filename)
                dbm = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(dbm)
                Configuration.set_persistent_var('db_version', version)
                migration_count = migration_count + 1
            except Exception as e:
                # throw a fit if it doesn't work
                raise e
    Logging.info(f"--- {migration_count if migration_count else 'no'} db migration{'' if migration_count == 1 else 's'} run")


def before_send(event, hint):
    if event['level'] == "error" and 'logger' in event.keys() and event['logger'] == 'gearbot':
        return None  # we send errors manually, in a much cleaner way
    if 'exc_info' in hint:
        exc_type, exc_value, tb = hint['exc_info']
        for t in [ConnectionClosed, ClientOSError, ServerDisconnectedError]:
            if isinstance(exc_value, t):
                return
    return event


def can_help(ctx):
    return ctx.author.guild_permissions.mute_members


if __name__ == '__main__':
    Logging.init()
    Logging.info("Launching Skybot!")

    dsn = Configuration.get_var('SENTRY_DSN', '')
    dsn_env = Configuration.get_var('SENTRY_ENV', 'Dev')
    Logging.info(f"DSN info - dsn:{dsn} env:{dsn_env}")
    if dsn != '':
        sentry_sdk.init(dsn, before_send=before_send, environment=dsn_env, integrations=[AioHttpIntegration()])

    # TODO: exception handling for db migration error
    run_db_migrations()
    Logging.info('dg migrations go')
    Database.init()
    Logging.info('db init go')

    intents = Intents(members=True, messages=True, guilds=True, bans=True, emojis=True, presences=True, reactions=True)
    loop = asyncio.get_event_loop()
    prefix = Configuration.get_var("bot_prefix")
    skybot = Skybot(
        command_prefix=commands.when_mentioned_or(prefix),
        case_insensitive=True,
        intents=intents,
        loop=loop)
    Logging.info('skybot instantiated')
    skybot.help_command = commands.DefaultHelpCommand(command_attrs=dict(name='snelp', checks=[can_help]))

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

    Logging.info("Skybot shutdown complete")
