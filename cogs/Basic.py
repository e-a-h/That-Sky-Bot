import time
from datetime import datetime, timezone
from enum import Enum
from logging import getLevelName
from typing import Optional, Union, Literal

import discord
from discord import app_commands, Interaction
from discord.app_commands import Choice
from discord.ext.commands import Context, Greedy, is_owner, guild_only, command, parameter

from cogs.BaseCog import BaseCog
from utils import Utils, Logging
from utils.Converters import EnumChoice
from utils.Helper import Sender
from utils.Logging import TCol
from utils.Utils import interaction_response, parse_date_with_pacific_fallback, check_is_owner


class SyncValues(Enum):
    Current = "~"
    GlobalToLocal = "*"
    ClearTree = "^"

    @classmethod
    def _missing_(cls, value):
        """Accept a member name (case-insensitive) as well as its symbol."""
        if isinstance(value, str):
            folded = value.casefold()
            for member in cls:
                if member.name.casefold() == folded:
                    return member
        return None

    @classmethod
    def help_text(cls) -> str:
        return ", ".join(f"[{member.value}] {member.name}" for member in cls)


class Basic(BaseCog):

    async def cog_check(self, ctx):
        return await Utils.permission_official_mute(ctx)

    async def cog_unload(self):
        Logging.info("unload Basic", TCol.Cyan)

    async def cog_load(self):
        Logging.info("load Basic", TCol.Cyan)

    @command(aliases=["ping"], hidden=True)
    async def ping_pong(self, ctx: Context):
        """show ping times"""
        t1 = time.perf_counter()
        message = await ctx.send(":ping_pong:")
        t2 = time.perf_counter()
        rest = round((t2 - t1) * 1000)
        latency = round(self.bot.latency * 1000, 2)
        await message.edit(
            content=f":hourglass: REST API ping is {rest} ms | Websocket ping is {latency} ms :hourglass:")

    @app_commands.command(description="Set log level")
    @app_commands.describe(
        level="The log level. Default is INFO.",
        logger="The logger. Default is BOT.")
    @app_commands.check(check_is_owner)
    @app_commands.default_permissions(manage_channels=True)
    async def set_log_level(
            self,
            interaction: Interaction,
            level: Optional[Logging.LogLevelOptions] = None,
            logger: Optional[Literal['BOT', 'DISCORD']] = None):
        """Set log level"""
        if not level:
            level = Logging.LogLevelOptions.INFO

        my_logger = Logging.LOGGER
        if logger == "DISCORD":
            my_logger = Logging.DISCORD_LOGGER

        Logging.debug(f"Basic/set_log_level: {level}", TCol.Cyan)
        Logging.set_level(level, my_logger)
        my_level = getLevelName(Logging.get_level(my_logger))
        await interaction_response(interaction).send_message(f"Log level set to {my_level}", ephemeral=True)

    @app_commands.command(description="Get discord time stamps")
    @app_commands.describe(request_formats="Available formats: d D t T f F R s")
    @guild_only()
    async def timestamp(
            self,
            interaction: Interaction,
            request_formats: str = "",
            date_time: str = ""):
        """Print a timestamp for the current or specified time.

        Parameters
        ----------
        interaction
        request_formats
            Available formats: d D t T f F R s
        date_time
            Date/Time in ISO-8601 Format: YYYY-MM-DD HH:MM:SS [+/-<:offset>]
            Assumes Pacific Time if no offset is specified.
        """
        if date_time:
            try:
                dt = parse_date_with_pacific_fallback(date_time)
            except ValueError:
                await interaction_response(interaction).send_message("Invalid date/time format", ephemeral=True)
                return
        else:
            dt = datetime.now(timezone.utc)

        now = int(dt.timestamp())
        formats = {
            'd': f"<t:{now}:d>",
            'D': f"<t:{now}:D>",
            't': f"<t:{now}:t>",
            'T': f"<t:{now}:T>",
            'f': f"<t:{now}:f>",
            'F': f"<t:{now}:F>",
            'R': f"<t:{now}:R>",
            's': f"{now}"
        }
        dates_formatted = []

        format_requested = False
        for arg in set(request_formats):
            if arg in formats:
                dates_formatted.append(f"`{formats[arg]}` {formats[arg]}")
                format_requested = True

        if not format_requested:
            for arg in formats:
                dates_formatted.append(f"`{formats[arg]}` {formats[arg]}")

        if dates_formatted:
            output = "\n".join(dates_formatted)
        else:
            output = "No valid format requested"

        await interaction_response(interaction).send_message(output, ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command()
    @app_commands.describe(
        operation=f"Sync type: {SyncValues.help_text()}",
        guild_id="Guild to sync to. Omit for global.")
    @app_commands.check(check_is_owner)
    @app_commands.default_permissions(manage_channels=True)
    async def sync_app_commands(
            self,
            interaction: Interaction,
            operation: Optional[SyncValues] = None,
            guild_id: Optional[int] = None) -> None:
        guilds = []
        if guild_id:
            for candidate_guild in self.bot.guilds:
                if candidate_guild.id == guild_id:
                    guilds = [candidate_guild.id]
                    break
        Logging.debug(f"Syncing --\n"
                      f"\tguilds: {guilds}\n"
                      f"\tspec: {operation.name if operation else 'global'}")
        await self.do_sync(interaction, guilds=guilds, spec=operation)

    @sync_app_commands.autocomplete('guild_id')
    async def guild_autocomplete(
            self,
            interaction: discord.Interaction,
            current: str) -> list[Choice[Union[int, str, float]]]:
        guilds = self.bot.guilds
        ret = [
            app_commands.Choice(name=guild.name, value=guild.id)
            for guild in guilds if current.lower() in guild.name.lower()
        ]
        return ret

    @is_owner()
    @guild_only()
    @command(
        aliases=["sync"],
        brief="Sync app commands by guild or globally",
        help="Sync app commands to the given guilds, or globally when no guild is given.")
    async def app_command_sync(
            self,
            ctx: Context,
            guilds: Greedy[discord.Object] = parameter(  # type: ignore
                default=None,
                description="Guilds to sync. Omit for global sync."),
            spec: Optional[SyncValues] = parameter(
                converter=EnumChoice(SyncValues),
                default=None,
                displayed_default="global",
                description=f"Sync type: {SyncValues.help_text()}")) -> None:
        """
        Sync commands by guild or globally

        Parameters
        -----------
        ctx
        guilds: list
            Guilds to sync. Omit for global sync
        spec: SyncValues
            Sync type, by name or symbol"""
        validated_guilds = []
        Logging.debug("guilds: "+repr(guilds))
        if guilds:
            for i in guilds:
                validated_guilds.append(i.id)
        Logging.debug("my_guilds: "+repr(validated_guilds))
        Logging.debug("spec: "+repr(spec))
        await self.do_sync(ctx, validated_guilds, spec)

    async def do_sync(self, ctx: Union[Context, Interaction], guilds: list[int], spec: Optional[SyncValues] = None) -> None:
        sender = Sender(ctx)
        guild = ctx.guild
        if guild is None:
            await sender.send("Sync failed. This command must be used in a guild.", ephemeral=True)
            return
        if not guilds:
            guild_arg = {"guild": guild}
            if spec is SyncValues.Current:
                Logging.debug("Syncing current guild")
            elif spec is SyncValues.GlobalToLocal:
                Logging.debug("Syncing global to local")
                self.bot.tree.copy_global_to(guild=guild)
            elif spec is SyncValues.ClearTree:
                Logging.debug("Clearing command tree")
                self.bot.tree.clear_commands(guild=guild)
            else:
                Logging.debug("Syncing globally")
                guild_arg = {}

            synced = await self.bot.tree.sync(**guild_arg)

            await sender.send(
                f"Synced {len(synced)} commands {'globally' if not spec else 'to the current guild.'}",
                ephemeral=True)
            return

        ret = 0
        Logging.debug("do guilds: " + repr(guilds))
        for guild_id in guilds:
            try:
                a_guild = self.bot.get_guild(guild_id)
                if a_guild is None or a_guild not in self.bot.guilds:
                    Logging.debug(f"Guild {guild_id} not found")
                    continue
                Logging.debug(f"Syncing guild {guild_id}")
                await self.bot.tree.sync(guild=a_guild)
            except discord.HTTPException:
                pass
            else:
                ret += 1

        await sender.send(f"Synced the tree to {ret}/{len(guilds)}.", ephemeral=True)

    ####
    # app command groups
    # fun_group = Group(
    #     name='fun',
    #     description='Reaction controls',
    #     default_permissions=Permissions(ban_members=True))
    #
    # subgroup = Group(parent=fun_group, name='unfun', description='sub group?')
    #
    # @fun_group.command(description="Bops a member")
    # @app_commands.describe(member="The member to bop")
    # async def bop(self, interaction: Interaction, member: discord.Member):
    #     await interaction_response(interaction).send_message(f"bop {member.mention}")
    #
    # @fun_group.command(description="Unbops a member")
    # @app_commands.describe(member="The member to unbop")
    # async def unbop(self, interaction: Interaction, member: discord.Member):
    #     await interaction_response(interaction).send_message(f"unbop {member.mention}")
    #
    # @subgroup.command(description="Slaps a member")
    # @app_commands.describe(member="the member to slap")
    # async def botslap(self, interaction: Interaction, member: discord.Member):
    #     await interaction_response(interaction).send_message(f"botslap {member.mention}")
    ####


async def setup(bot):
    await bot.add_cog(Basic(bot))
