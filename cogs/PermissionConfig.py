import asyncio
from datetime import datetime, timezone
from itertools import islice
from typing import Union

import discord
from discord import Permissions, Role
from discord import app_commands
from discord.app_commands import AppCommandError, Choice, Group
from discord.ext import commands
from discord.ext.commands import Context

from cogs.BaseCog import BaseCog
from discord.interactions import Interaction
from utils import Lang, Logging
from utils import Utils
from utils.Database import AdminRole, BotAdmin, Guild, ModRole, TrustedRole, UserPermission
from utils.Helper import Sender
from utils.Logging import TCol
from utils.Utils import guild_log, interaction_response, check_is_owner


class PermissionConfig(BaseCog):
    def __init__(self, bot):
        self.admin_roles = dict()
        self.mod_roles = dict()
        self.trusted_roles = dict()
        self.command_permissions = dict()
        self.after_ready_task = None
        super().__init__(bot)

    def init_permissions(self):
        self.admin_roles = dict()
        self.mod_roles = dict()
        self.trusted_roles = dict()
        self.command_permissions = dict()

    async def cog_unload(self):
        await self.after_ready_task

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        self.after_ready_task = asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        for guild in self.bot.guilds:
            self.init_guild(guild)
        for guild in self.bot.guilds:
            await self.load_guild(guild)

    def init_guild(self, guild):
        self.admin_roles[guild.id] = set()
        self.mod_roles[guild.id] = set()
        self.trusted_roles[guild.id] = set()
        self.command_permissions[guild.id] = dict()

    async def load_guild(self, guild):
        guild_row, created = await Guild.get_or_create(serverid=guild.id)
        try:
            for row in await guild_row.admin_roles:
                role = guild.get_role(row.roleid)
                if role:
                    self.admin_roles[guild.id].add(role.id)
                else:
                    await row.delete()
            for row in await guild_row.mod_roles:
                role = guild.get_role(row.roleid)
                if role:
                    self.mod_roles[guild.id].add(role.id)
                else:
                    await row.delete()
            for row in await guild_row.trusted_roles:
                role = guild.get_role(row.roleid)
                if role:
                    self.trusted_roles[guild.id].add(role.id)
                else:
                    await row.delete()
            for row in await guild_row.command_permissions:
                member = guild.get_member(row.userid)
                if member:
                    self.command_permissions[guild.id][member.id] = row
                else:
                    await row.delete()
        except KeyError:
            Logging.info(f"Role loading failed in {guild.id}", TCol.Fail)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.admin_roles[guild.id]
        del self.mod_roles[guild.id]
        del self.trusted_roles[guild.id]
        del self.command_permissions[guild.id]

        # remove all configured guild permissions
        guild_row = await self.bot.get_guild_db_config(guild.id)
        await guild_row.admin_roles.filter().delete()
        await guild_row.mod_roles.filter().delete()
        await guild_row.trusted_roles.filter().delete()
        await guild_row.command_permissions.filter().delete()

    async def cog_check(self, ctx):
        # Minimum permission for all permissions commands: manage_server
        if ctx.guild:
            if ctx.author.guild_permissions.manage_guild or await Utils.permission_manage_bot(ctx):
                return True
            for role in ctx.author.roles:
                if role.id in self.admin_roles[ctx.guild.id]:
                    return True
        if await Utils.permission_manage_bot(ctx):
            return True
        return False

    async def send_permissions_list(self, ctx: Union[Context, Interaction]):
        guild = ctx.guild
        assert isinstance(guild, discord.Guild)  # Guild type is assumed (invoking commands are guild-only)
        is_bot_admin = await Utils.permission_manage_bot(ctx)

        embed = discord.Embed(
            timestamp=datetime.now(timezone.utc),
            color=0x663399,
            title=Lang.get_locale_string("permission_config/info", ctx, server_name=guild.name))
        embed.add_field(name='Configurable Permissions',
                        value=f"Trusted Roles, Mod Roles, Admin Roles{', Bot Admins' if is_bot_admin else ''}",
                        inline=False)

        admin_roles = set()
        mod_roles = set()
        trusted_roles = set()
        user_permissions = set()

        guild_row = await Guild.get(serverid=guild.id)

        for row in await guild_row.admin_roles:
            role = guild.get_role(row.roleid)
            if role:
                admin_roles.add(role.mention)
        for row in await guild_row.mod_roles:
            role = guild.get_role(row.roleid)
            if role:
                mod_roles.add(role.mention)
        for row in await guild_row.trusted_roles:
            role = guild.get_role(row.roleid)
            if role:
                trusted_roles.add(role.mention)
        for row in await guild_row.command_permissions:
            member = guild.get_member(row.userid)
            if member:
                member_desc = Utils.get_member_log_name(member)
                desc = f"{member_desc} - `{'ALLOW' if row.allow else 'DENY'}`: `{row.command}`"
                user_permissions.add(desc)

        no_roles_string = "None"

        embed.add_field(name="Admin Roles", value='\n'.join(admin_roles) if len(admin_roles) > 0 else no_roles_string, inline=False)
        embed.add_field(name="Mod Roles", value='\n'.join(mod_roles) if len(mod_roles) > 0 else no_roles_string, inline=False)
        embed.add_field(name="Trusted Roles", value='\n'.join(trusted_roles) if len(trusted_roles) > 0 else no_roles_string, inline=False)
        embed.add_field(name="User Permissions", value='\n'.join(user_permissions) if len(user_permissions) > 0 else no_roles_string, inline=False)

        if is_bot_admin:
            bot_admins = set()
            for row in await BotAdmin.all():
                user = self.bot.get_user(row.userid)
                if user:
                    bot_admins.add(f"{user.mention} {str(user)} ({user.id})")
                else:
                    await guild_log(
                        guild.id,
                        f"PermissionConfig Could not find user {row.userid}."
                        f" If they left the server, they should probably be removed from guild permissions")
            embed.add_field(name="Bot Admins", value='\n'.join(bot_admins) if len(bot_admins) > 0 else no_roles_string, inline=False)

        sender = Sender(ctx)
        await sender.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    # Map role level name to (db model, related_name attr on Guild, in-memory cache attr)
    ROLE_LEVELS = {
        'admin': (AdminRole, 'admin_roles'),
        'mod': (ModRole, 'mod_roles'),
        'trusted': (TrustedRole, 'trusted_roles'),
    }

    ####################
    # App Commands
    ####################

    permissions_group = Group(
        name='permissions',
        description='Permissions configuration',
        guild_only=True,
        default_permissions=Permissions(ban_members=True))

    @permissions_group.command(name='list')
    async def list_permissions(self, interaction: Interaction) -> None:
        """List custom commands"""
        await self.send_permissions_list(interaction)

    @permissions_group.command(name='reload')
    async def reload(self, interaction: Interaction) -> None:
        """Reload custom commands"""
        self.init_permissions()
        await self.cog_load()
        sender = Sender(interaction)
        await sender.send("reloaded permissions from db...")
        await self.list_permissions(interaction)

    @permissions_group.command(name='set_user_permission')
    async def set_user_permission(
            self,
            interaction: Interaction,
            user: discord.Member,
            command: str,
            value: bool) -> None:
        """Add or edit a user permission for a named command"""
        guild = interaction.guild
        assert isinstance(guild, discord.Guild)  # guild_only

        guild_row, _ = await Guild.get_or_create(serverid=guild.id)
        row, created = await UserPermission.get_or_create(
            guild=guild_row, userid=user.id, command=command,
            defaults={'allow': value})
        if not created:
            row.allow = value
            await row.save()
        self.command_permissions[guild.id][user.id] = row

        verb = 'added' if created else 'updated'
        member_desc = Utils.get_member_log_name(user)
        await interaction_response(interaction).send_message(
            f"{verb} permission for {member_desc}: `{'ALLOW' if value else 'DENY'}`: `{command}`",
            ephemeral=True)

    @permissions_group.command(name='remove_user_permission')
    async def remove_user_permission(
            self,
            interaction: Interaction,
            user: discord.Member,
            command: str) -> None:
        """Remove a user permission for a named command"""
        guild = interaction.guild
        assert isinstance(guild, discord.Guild)  # guild_only

        guild_row, _ = await Guild.get_or_create(serverid=guild.id)
        row = await UserPermission.get_or_none(guild=guild_row, userid=user.id, command=command)
        if row is None:
            await interaction_response(interaction).send_message(
                f"No permission for {Utils.get_member_log_name(user)} on `{command}`",
                ephemeral=True)
            return
        await row.delete()
        self.command_permissions[guild.id].pop(user.id, None)
        await interaction_response(interaction).send_message(
            f"Removed permission for {Utils.get_member_log_name(user)} on `{command}`",
            ephemeral=True)

    @permissions_group.command(name='add_role')
    async def add_role(self, interaction: Interaction, level: str, role: Role) -> None:
        """Add a role to admin, mod, or trusted"""
        guild = interaction.guild
        assert isinstance(guild, discord.Guild)  # guild_only

        my_level = self._validate_level(guild, level)

        model, cache_attr = self.ROLE_LEVELS[my_level]
        guild_row, _ = await Guild.get_or_create(serverid=guild.id)
        _, created = await model.get_or_create(guild=guild_row, roleid=role.id)
        getattr(self, cache_attr)[guild.id].add(role.id)

        if created:
            msg = f"Added {role.mention} to `{my_level}` roles"
        else:
            msg = f"{role.mention} is already a `{my_level}` role"
        await interaction_response(interaction).send_message(
            msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @permissions_group.command(name='remove_role')
    async def remove_role(self, interaction: Interaction, level: str, role: Role) -> None:
        """Remove a role from admin, mod, or trusted"""
        guild = interaction.guild
        assert isinstance(guild, discord.Guild)  # guild_only

        my_level = self._validate_level(guild, level)

        model, cache_attr = self.ROLE_LEVELS[my_level]
        guild_row, _ = await Guild.get_or_create(serverid=guild.id)
        row = await model.get_or_none(guild=guild_row, roleid=role.id)
        getattr(self, cache_attr)[guild.id].discard(role.id)
        if row is None:
            await interaction_response(interaction).send_message(
                f"{role.mention} is not a `{my_level}` role", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
            return
        await row.delete()
        await interaction_response(interaction).send_message(
            f"Removed {role.mention} from `{my_level}` roles", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())

    def _validate_level(self, guild: Guild, level: str):
        my_level = level.lower()
        if my_level not in self.ROLE_LEVELS:
            raise AppCommandError(f"Level must be one of `{', '.join(self.ROLE_LEVELS)}`")
        return my_level

    ####################
    # bot admin commands
    ####################

    @permissions_group.command(name='add_bot_admin')
    async def add_bot_admin(self, interaction: Interaction, user: discord.User) -> None:
        """Add a user to bot admins (bot admin only)"""
        if not await Utils.permission_manage_bot(interaction):
            raise app_commands.MissingPermissions([""])
        _, created = await BotAdmin.get_or_create(userid=user.id)
        if created:
            msg = f"Added {user.mention} to bot admins"
        else:
            msg = f"{user.mention} is already a bot admin"
        await interaction_response(interaction).send_message(
            msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @permissions_group.command(name='remove_bot_admin')
    async def remove_bot_admin(self, interaction: Interaction, user: discord.User) -> None:
        """Remove a user from bot admins (bot admin only)"""
        if not await Utils.permission_manage_bot(interaction):
            raise app_commands.MissingPermissions([""])
        row = await BotAdmin.get_or_none(userid=user.id)
        if row is None:
            await interaction_response(interaction).send_message(
                f"{user.mention} is not a bot admin", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
            return
        await row.delete()
        await interaction_response(interaction).send_message(
            f"Removed {user.mention} from bot admins", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())

    ####################
    # autocomplete
    ####################

    @add_role.autocomplete('level')
    @remove_role.autocomplete('level')
    async def level_autocomplete(self, interaction: Interaction, current: str) -> list[Choice[Union[str, int, float]]]:
        return [Choice(name=lvl, value=lvl)
                for lvl in self.ROLE_LEVELS if current.lower() in lvl]


async def setup(bot):
    await bot.add_cog(PermissionConfig(bot))
