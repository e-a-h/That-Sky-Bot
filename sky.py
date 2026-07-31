"""
A discord bot module for managing scheduled tasks, database interaction, bot events, and configurations,
cog management, monitoring integrations, and event handling.

Classes
-------
Skybot : discord.ext.commands.Bot
    A specialized subclass of Bot to handle the bot's lifecycle, events, extensions, and configuration.
"""
import asyncio
import os
import signal
import sys
import traceback
from typing import Optional
from asyncio import shield, iscoroutinefunction

import sentry_sdk
from aerich import Command
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import ConnectionClosed, Intents, AllowedMentions, Member, ClientUser
from discord.ext import commands, tasks
from discord.ext.commands import Bot, DefaultHelpCommand
from prometheus_client import CollectorRegistry
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from tortoise import Tortoise

import utils.tortoise_settings
from utils import Logging, Configuration, Constants, Utils, Emoji, Database, Lang, dbbackup, UserActionRegister
from utils.Database import BotAdmin
from utils.Logging import TCol
from utils.PrometheusMon import PrometheusMon
from utils.Tree import CustomCommandTree
from utils.UserActionRegister import StopUserActionButton

running = None



class Skybot(Bot):
    """
    A discord bot that handles scheduled tasks, manages cogs, database interactions,
    and bot-specific events and configurations.

    Attributes
    ----------
    loaded : bool
        Indicates whether the bot has finished its loading process.
    metrics_reg : CollectorRegistry
        The Prometheus registry object used for bot-related monitoring metrics.
    data : dict
        A general-purpose dictionary for storing miscellaneous bot data.
    """
    loaded = False
    metrics_reg = CollectorRegistry()
    data = {}

    def __init__(self, *args, loop=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.shutting_down = False
        self.metrics = PrometheusMon(self)
        self.config_channels = {}
        self.db_keepalive = None
        self.my_name = type(self).__name__
        self.loaded = False
        self.help_command: DefaultHelpCommand
        sys.path.append(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "sky-python-music-sheet-maker",
                         "python"))

    @tasks.loop(seconds=1.0)
    async def check_expirations(self):
        """loop to check expirations. register expiration checks here!"""
        await UserActionRegister.check_expiration()

    async def setup_hook(self):
        Logging.info('setup_hook start', TCol.Warning)

        await Database.init()
        Logging.info('db init is done')

        await Lang.load_local_overrides()
        Logging.info(
            f"Locales loaded\n"
            f"\tguild: {Lang.GUILD_LOCALES}\n"
            f"\tchannel: {Lang.CHANNEL_LOCALES}")

        # Register dynamic classes
        self.add_dynamic_items(StopUserActionButton)

        for cog in Configuration.get_var("cogs"):
            try:
                Logging.info(f"load cog {TCol.Cyan.value}{cog}{TCol.End.value}")
                await self.load_extension("cogs." + cog)
                Logging.info("\tloaded", TCol.Green)
            except Exception as e:
                msg = (f"{TCol.Fail.value}Failed to load cog{TCol.End.value} "
                       f"{TCol.Warning.value}{cog}{TCol.End.value}")
                await Utils.handle_exception(msg, e)
        Logging.info("Cog loading complete", TCol.Bold, TCol.Green)
        self.db_keepalive = self.loop.create_task(self.keep_db_alive())
        self.loaded = True
        Logging.info('setup_hook end', TCol.Underline, TCol.Warning)

    async def on_ready(self):
        """
        Executed once the bot is ready.
        """
        global running
        Logging.info('on_ready start', TCol.Underline, TCol.Warning)

        Logging.BOT_LOG_CHANNEL = self.get_channel(Configuration.get_var("log_channel"))
        Emoji.initialize(self)
        if not self.check_expirations.is_running():
            self.check_expirations.start()

        if running:
            Logging.info(
                f"{Configuration.get_var('bot_name', 'this bot')} gateway reconnected")
        else:
            await Logging.bot_log(
                f"{Configuration.get_var('bot_name', 'this bot')} startup complete")

        running = True
        Logging.info(f"{self.my_name} on_ready complete", TCol.Underline, TCol.Warning)

    async def close(self):
        Logging.info("Shutting down?")
        if not self.shutting_down:
            await Logging.bot_log(
                f"{Configuration.get_var('bot_name', 'this bot')} shutting down...")
            Logging.info("Shutting down...")
            self.shutting_down = True
            self.check_expirations.cancel()

            for cog in list(self.cogs):
                Logging.info(
                    f"{TCol.Warning.value}Shutting down{TCol.End.value} cog "
                    f"{TCol.Cyan.value}{cog}{TCol.End.value}")
                c = self.get_cog(cog)
                try:
                    call_shutdown = getattr(c, "shutdown")
                    if iscoroutinefunction(call_shutdown):
                        await call_shutdown()
                except AttributeError:
                    pass
                Logging.info(
                    f"{TCol.Warning.value}unloading{TCol.End.value} cog "
                    f"{TCol.Cyan.value}{cog}{TCol.End.value}")
                await self.unload_extension(f"cogs.{cog}")
                Logging.info("\tunloaded", TCol.Warning)
            Logging.info("All cogs unloaded", TCol.Warning)

            if self.db_keepalive:
                self.db_keepalive.cancel()
            await Tortoise.close_connections()
            Logging.info("DB connection closed", TCol.Warning)

        return await super().close()

    async def on_command_error(self, ctx: commands.Context, error):
        if ctx and ctx.command is not None and hasattr(self.help_command, "get_command_signature"):
            try:
                signature = self.help_command.get_command_signature(ctx.command)
            except AttributeError:
                signature = "[unknown command signature]"
        else:
            signature = "[unknown command signature]"

        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(str(error))
        elif isinstance(error, commands.CheckFailure):
            pass
        elif isinstance(error, commands.CommandOnCooldown):
            if ctx.command and ctx.command.name in ['krill']:
                # commands in this list have custom cooldown handler
                return
            await ctx.send(str(error))
        elif isinstance(error, commands.MaxConcurrencyReached):
            await ctx.send(
                f"Too many people are using the `{ctx.invoked_with}` command right now."
                f" Try again later")
        elif isinstance(error, commands.MissingRequiredArgument):
            self.help_command.context = ctx
            param_name = ctx.current_parameter.name if ctx.current_parameter else "[unknown parameter]"
            await ctx.send(
                f"""
{Emoji.get_chat_emoji('NO')} You are missing a required command argument:
 `{param_name}`
{Emoji.get_chat_emoji('WRENCH')} Command usage: `{signature}`
                """)
        elif isinstance(error, commands.BadArgument):
            self.help_command.context = ctx
            param_name = ctx.current_parameter.name if ctx.current_parameter else "[unknown parameter]"
            await ctx.send(
                f"""
{Emoji.get_chat_emoji('NO')} Failed to parse the
 ``{param_name}`` parameter: ``{error}``
{Emoji.get_chat_emoji('WRENCH')} Command usage: `{signature}`
                """)
        elif isinstance(error, commands.BadLiteralArgument):
            self.help_command.context = ctx
            await ctx.send(f"Parameter `{error.param.name}` must be one of "
                           f"`{', '.join(error.literals)}` but you said `{error.argument}`")
        elif isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.UnexpectedQuoteError):
            self.help_command.context = ctx
            await ctx.send(
                f"""
{Emoji.get_chat_emoji('NO')} There are quotes in there that I don't like
{Emoji.get_chat_emoji('WRENCH')} Command usage: `{signature}`
                """)
        else:
            await Utils.handle_exception(
                "Command execution failed",
                error.original if hasattr(error, "original") else error,
                ctx=ctx)
            # notify caller
            e = Emoji.get_chat_emoji('BUG')
            if isinstance(ctx.me, ClientUser) or isinstance(ctx.me, Member) and ctx.channel.permissions_for(ctx.me).send_messages:
                await ctx.send(f"{e} Something went wrong while executing that command {e}")

    async def keep_db_alive(self):
        """
        Keeps the database connection active by periodically executing a simple query.

        This coroutine ensures that the database connection remains alive and does not time out by
        sending a periodic query to the database. The loop continues indefinitely unless the
        connection is closed.

        Raises
        ------
        No return value is specified for this function.
        """
        while not self.is_closed():
            # simple query to ping the db
            query = "select 1"
            conn = Tortoise.get_connection("default")
            await conn.execute_query(query)
            await asyncio.sleep(3600)

    async def member_is_admin(self, member_id: int):
        """
        Determine if a member has administrative privileges.

        This function checks whether a specified member is an administrator by
        verifying if they are an owner, a database admin, or exist in a
        predefined list of administrators.

        Parameters
        ----------
        member_id : int
            The unique identifier of the member whose admin status is being checked.

        Returns
        -------
        bool
            True if the member is an administrator; False otherwise.
        """
        my_user = self.get_user(member_id)
        if not my_user:
            return False
        is_owner = await self.is_owner(my_user) if my_user else False
        is_db_admin = await BotAdmin.get_or_none(userid=member_id) is not None
        in_admins = member_id in Configuration.get_var("ADMINS", [])
        caller = traceback.extract_stack(limit=2)[0]
        Logging.debug(f"member_is_admin called from {caller.filename}:{caller.lineno} in {caller.name}\n"
                      f"{Utils.get_member_log_name(my_user)}\n"
                      f"\towner: {'yes' if is_owner else 'no'}\n"
                      f"\tdb_admin: {'yes' if is_db_admin else 'no'}\n"
                      f"\tin_admins: {'yes' if in_admins else 'no'}")
        return is_db_admin or is_owner or in_admins

    async def get_guild_db_config(self, guild_id) -> Database.Guild:
        """
        Retrieves the database configuration for a specific guild.

        This function attempts to fetch the guild configuration from an in-memory
        cache. If the configuration is not in the cache, it queries the database
        to either retrieve or create the guild configuration. The fetched
        configuration is then stored in the cache for future use.

        Parameters
        ----------
        guild_id : int
            The unique identifier of the guild.

        Returns
        -------
        Database.Guild
            The configuration row for the guild if it exists or is created
            successfully

        Raises
        ------
        Exception
            If an error occurs while fetching or creating the guild configuration.
        """
        try:
            if guild_id in Utils.GUILD_CONFIGS:
                guild_row = Utils.GUILD_CONFIGS[guild_id]
                return guild_row
            row, created = await Database.Guild.get_or_create(serverid=guild_id)
            Utils.GUILD_CONFIGS[guild_id] = row
            return row
        except Exception as e:
            raise Exception(f"Failed to get guild config for {guild_id}") from e


async def run_db_migrations():
    """
    Executes database migrations asynchronously.

    This function initializes and performs Tortoise ORM database migrations using configuration
    stored within the application. If an error occurs during execution, the bot will not run.

    Raises
    ------
    SystemExit
        Exits the program with a status code of `1` if a migration-related error occurs.
    """
    try:
        Logging.info('######## dg migrations ########', TCol.Underline, TCol.Blue)
        command = Command(
            tortoise_config=utils.tortoise_settings.TORTOISE_ORM,
            app=Constants.APP_NAME,
        )
        await command.init()
        result = await command.upgrade(False)
        if result:
            Logging.info("##### db migrations done: #####", TCol.Green)
            Logging.info(result)
        else:
            Logging.info("##### no migrations found #####", TCol.Warning)
    except Exception as e:
        Utils.get_embed_and_log_exception("DB migration failure", e)
        sys.exit(1)
    Logging.info('###### end dg migrations ######', TCol.Green)


def before_send(event, hint):
    """exclude some exceptions from sentry reporting"""
    if 'exc_info' in hint:
        exc_type, exc_value, tb = hint['exc_info']
        # Don't report these exceptions to sentry
        for t in [ConnectionClosed, ClientOSError, ServerDisconnectedError]:
            if isinstance(exc_value, t):
                return None
    return event


async def persistent_data_job(work_item: Configuration.PersistentAction):
    """Perform persistent data i/o job

    Parameters
    ----------
    work_item: Configuration.PersistentAction
    """
    Configuration.do_persistent_action(work_item)


async def queue_worker(name, queue, job, shielded=False):
    """Generic queue worker

    Parameters
    ----------
    name
    queue:
        the queue to pull work items from
    job:
        the job that will be done on work items
    shielded:
        boolean indicating whether the job will be shielded from cancellation
    """
    global running
    global this_bot
    try:
        # Logging.info(
        # f"\t{TCol.cOkGreen}start{TCol.cEnd} {TCol.cOkCyan}`{name}`{TCol.cEnd} worker")
        while True:
            # Get a work_item from the queue
            work_item = await queue.get()
            try:
                if shielded:
                    await shield(job(work_item))
                else:
                    await asyncio.create_task(job(work_item))
            except asyncio.CancelledError:
                Logging.info(f"job canceled for worker {name}")
                if not this_bot:
                    Logging.info(f"stopping worker {name}")
                    raise
                Logging.info(f"worker {name} continues")
            except Exception as e:
                await Utils.handle_exception("worker unexpected exception", e)
            queue.task_done()
    finally:
        # Logging.info(f"{name} worker is finished")
        pass
    return


async def main():
    """
    The main entry point of the application that initializes and starts the bot.

    This asynchronous function is responsible for setting up the bot environment, initializing
    logging and monitoring, configuring integrations such as Sentry, performing database
    operations, and scheduling queue workers. It also establishes signal handlers, starts the
    bot client with the provided token, and handles graceful shutdown of the application.

    The bot uses custom configurations, features persistent queue handling, and supports
    intents to interact with Discord events. Essential application functionalities, such as
    database backups and migrations, are executed within this function before starting the
    bot.

    Notes
    -----
    The function uses global variables (`running` and `this_bot`). These are altered during
    execution to indicate the bot's status or to facilitate its functionality.

    Raises
    ------
    KeyboardInterrupt
        Raised when SIGINT or SIGTERM signals are received, triggering the shutdown process.

    See Also
    --------
    queue_worker : The worker function used by the persistent queue for handling tasks.
    """
    # start_monitoring(seconds_frozen=10, test_interval=100)

    global running
    Logging.init()
    Logging.info(f"Launching {Configuration.get_var('bot_name', 'this bot')}!")
    my_token = Configuration.get_var("token")

    dsn = Configuration.get_var('SENTRY_DSN', '')
    dsn_env = Configuration.get_var('SENTRY_ENV', 'Dev')
    Logging.info(f"DSN info - dsn:{dsn} env:{dsn_env}")

    if dsn != '':
        sentry_sdk.init(
            dsn,
            before_send=before_send,
            environment=dsn_env,
            integrations=[AioHttpIntegration()])

    # perform db backup before any connections are made to db
    dbbackup.backup_database()

    loop = asyncio.get_running_loop()
    await run_db_migrations()

    # A queue to handle changes to persistent storage
    # asynchronously and prevent collisions
    Configuration.PERSISTENT_AIO_QUEUE = asyncio.Queue()
    persistent_data_task = asyncio.create_task(
        queue_worker("Persistent Queue",
                     Configuration.PERSISTENT_AIO_QUEUE,
                     persistent_data_job))

    # start the client
    prefix = Configuration.get_var("bot_prefix")
    intents = Intents(
        members=True,
        messages=True,
        guild_messages=True,
        dm_messages=True,
        dm_typing=False,
        guild_typing=False,
        message_content=True,
        guilds=True,
        bans=True,
        emojis_and_stickers=True,
        presences=False,
        reactions=True)
    global this_bot
    this_bot = Skybot(
        loop=loop,
        command_prefix=commands.when_mentioned_or(prefix),
        case_insensitive=True,
        tree_cls=CustomCommandTree,
        allowed_mentions=AllowedMentions(
            everyone=False,
            users=True,
            roles=False,
            replied_user=True),
        intents=intents)
    this_bot.help_command = commands.DefaultHelpCommand(
        command_attrs={"name": "snelp", "checks": [Utils.can_help]})
    Utils.BOT = this_bot

    def close_bot():
        global this_bot
        if this_bot:
            Logging.info("sending close signal")
            asyncio.ensure_future(this_bot.close())

    try:
        for this_signal in (signal.SIGINT, signal.SIGTERM):
            # noinspection PyTypeChecker
            loop.add_signal_handler(this_signal, close_bot)
    except (NotImplementedError, AttributeError):
        pass

    try:
        if this_bot:
            async with this_bot:
                await this_bot.start(my_token)
    except KeyboardInterrupt:
        pass
    finally:
        this_bot.loaded = False
        running = False
        Logging.info("shutdown finally?", TCol.Warning)
        # Wait until all queued jobs are done, then cancel worker.
        if Configuration.PERSISTENT_AIO_QUEUE.qsize() > 0:
            Logging.info(
                f"there are {Configuration.PERSISTENT_AIO_QUEUE.qsize()}"
                f" persistent data items left..."
            )
            await Configuration.PERSISTENT_AIO_QUEUE.join()
        persistent_data_task.cancel("shutdown")
        try:
            await persistent_data_task
        except asyncio.CancelledError:
            pass

        if not this_bot.is_closed():
            await this_bot.close()

this_bot: Optional[Skybot] = None

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        # Who knows... log this.
        Logging.error(f"Unhandled exception: {ex}")
    finally:
        Logging.info("bot shutdown complete", TCol.Green)
