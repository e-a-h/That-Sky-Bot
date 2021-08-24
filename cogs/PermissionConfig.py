import discord
from discord import Role
from discord import guild
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Lang
from utils.Database import Guild, BotAdmin, TrustedRole
from utils import Utils


class PermissionConfig(BaseCog):
    admin_roles = dict()
    mod_roles = dict()
    trusted_roles = dict()
    command_permissions = dict()

    def __init__(self, bot):
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        for guild in self.bot.guilds:
            self.init_guild(guild)
            self.load_guild(guild)

    def init_guild(self, guild):
        self.admin_roles[guild.id] = set()
        self.mod_roles[guild.id] = set()
        self.trusted_roles[guild.id] = set()
        self.command_permissions[guild.id] = dict()

    def load_guild(self, guild):
        guild_row = Guild.get_or_create(serverid=guild.id)[0]
        for row in guild_row.admin_roles:
            role = guild.get_role(row.roleid)
            if role:
                self.admin_roles[guild.id].add(role.id)
            else:
                row.delete_instance()
        for row in guild_row.mod_roles:
            role = guild.get_role(row.roleid)
            if role:
                self.mod_roles[guild.id].add(role.id)
            else:
                row.delete_instance()
        for row in guild_row.trusted_roles:
            role = guild.get_role(row.roleid)
            if role:
                self.trusted_roles[guild.id].add(role.id)
            else:
                row.delete_instance()
        for row in guild_row.command_permissions:
            member = guild.get_member(row.userid)
            if member:
                self.command_permissions[guild.id][member.id] = row
            else:
                row.delete_instance()

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
        guild_row = self.bot.get_guild_db_config(guild.id)
        for row in guild_row.admin_roles:
            row.delete_instance()
        for row in guild_row.mod_roles:
            row.delete_instance()
        for row in guild_row.trusted_roles:
            row.delete_instance()
        for row in guild_row.command_permissions:
            row.delete_instance()

    async def cog_check(self, ctx):
        # Minimum permission for all permissions commands: manage_server
        if ctx.guild:
            if ctx.author.guild_permissions.manage_guild:
                return True
            for role in ctx.author.roles:
                if role.id in self.admin_roles[ctx.guild.id]:
                    return True
        if await self.bot.permission_manage_bot(ctx):
            return True
        return False

    @commands.group(name="permission_config", aliases=["permission", "permissions"], invoke_without_command=True)
    @commands.guild_only()
    async def permission_config(self, ctx):
        is_bot_admin = await self.bot.permission_manage_bot(ctx)

        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("permission_config/info", ctx, server_name=ctx.guild.name))
        embed.add_field(name='Configurable Permissions',
                        value=f"Trusted Roles, Mod Roles, Admin Roles{', Bot Admins' if is_bot_admin else ''}",
                        inline=False)

        admin_roles = set()
        mod_roles = set()
        trusted_roles = set()
        user_permissions = set()

        guild_row = Guild.get(serverid=ctx.guild.id)

        for row in guild_row.admin_roles:
            role = ctx.guild.get_role(row.roleid)
            if role:
                admin_roles.add(role.mention)
        for row in guild_row.mod_roles:
            role = ctx.guild.get_role(row.roleid)
            if role:
                mod_roles.add(role.mention)
        for row in guild_row.trusted_roles:
            role = ctx.guild.get_role(row.roleid)
            if role:
                trusted_roles.add(role.mention)
        for row in guild_row.command_permissions:
            member = ctx.guild.get_member(row.userid)
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
            for row in BotAdmin.select():
                user = self.bot.get_user(row.userid)
                bot_admins.add(f"{user.mention} {str(user)} ({user.id})")
            embed.add_field(name="Bot Admins", value='\n'.join(bot_admins) if len(bot_admins) > 0 else no_roles_string, inline=False)

        await ctx.send(embed=embed)

    @permission_config.command()
    @commands.guild_only()
    async def reload(self, ctx: commands.Context):
        await self.startup_cleanup()
        await ctx.send("reloaded permissions from db...")
        await ctx.invoke(self.permission_config)

    @permission_config.command()
    @commands.guild_only()
    async def add_trusted_role(self, ctx, role: Role):
        '''add a role to trusted_roles list for this guild'''
        guildid = ctx.guild.id
        if role.id in self.trusted_roles[guildid]:
            # if role already here, then it has to be in db because that's where we fetched from
            await ctx.send("role already there!")
            return
        self.trusted_roles[guildid].add(role.id)
        guild_row = Guild.get_or_create(serverid=guildid)[0]
        role_row = TrustedRole.create(guild=guild_row, roleid=role.id)
        role_row.save()
        await ctx.send(f"role added!")
        #TODO: add more checks for edge cases/errors???
        #TODO: make sure duplicates can't be inserted
        # consider how to ensure memory and db are in sync?
        #TODO: names long and not very friendly. is there any better?
        #TODO: bot response strings should use Lang files

    @permission_config.command()
    @commands.guild_only()
    async def remove_trusted_role(self, ctx, role: Role):
        '''remove a role from trusted_roles list for this guild'''
        guildid = ctx.guild.id
        if not role.id in self.trusted_roles[guildid]:
            await ctx.send("role not there!")
            return
        try:
            self.trusted_roles[guildid].discard(role.id)
            guild_row = Guild.get_or_create(serverid=guildid)[0]
            role_row = TrustedRole.get(guild=guild_row, roleid=role.id)
            role_row.delete_instance()
            await ctx.send(f"role removed!")
        except Exception as e:
            await ctx.send("removing failed")
    # see todos for add_trusted_role

    # TODO: set user permission
    # TODO: add role to [admin|mod|trusted]
    # TODO: add user to bot_admins

    # TODO: method for checking if user has permission that accepts ctx with command info?

def setup(bot):
    bot.add_cog(PermissionConfig(bot))
