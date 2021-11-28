import discord
from discord import Role, User, Member
from discord import guild
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Lang
from utils.Database import Guild, BotAdmin, TrustedRole, AdminRole, ModRole, UserPermission
from utils import Utils

#TODO: better perms around bot admin, shouldn't be able to change server settings and stuff?
#TODO: change to fetch strings form Lang
#TODO: command names long and not the easiest to type. is there any better?
class PermissionConfig(BaseCog):
    admin_roles = dict()
    mod_roles = dict()
    trusted_roles = dict()
    command_permissions = dict()
    bot_admin = set()

    def __init__(self, bot):
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        '''load info for permissions for all guilds bot is in'''
        self.bot_admin = set()
        for row in BotAdmin.select():
            self.bot_admin.add(row.userid)
        for guild in self.bot.guilds:
            self.init_guild(guild)
            self.load_guild(guild)

    def init_guild(self, guild):
        self.admin_roles[guild.id] = set()
        self.mod_roles[guild.id] = set()
        self.trusted_roles[guild.id] = set()
        self.command_permissions[guild.id] = dict()

    def load_guild(self, guild):
        '''load from database all admin, mod, and trusted roles, and command overrides for given guild. When loading, if bot can't find the role or member
        in the guild, it deletes the row from DB.
        
        guild: guild object that we want to load role info for.
        '''
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
                if member.id not in self.command_permissions[guild.id]:
                    self.command_permissions[guild.id][member.id] = dict()
                if row.command not in self.command_permissions[guild.id][member.id]:
                    self.command_permissions[guild.id][member.id][row.command] = row.allow
            else:
                row.delete_instance()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        #remove local cached guild permission info
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

    def check_member_in_list(self, guild, member, local_list):
        '''
        checks if given member has a role in the given list for the given guild.

        guild: guild object member is in and want to know if member is admin, mod, or trusted in
        member: Must be a guild member object, and member of the given guild parameter
        local_list: one of the dictionaries of this cog: admin_roles, mod_roles, trusted_roles. 
        '''
        if guild.id not in local_list:
            return False
        for role in member.roles:
                if role.id in local_list[guild.id]:
                    return True
        return False

    def is_admin(self, guild, userID, minimum:bool = False):
        '''checks if user with given userID is an admin in the given guild. Member either has manage guild permissions or
        a role that is considered an admin in this server

        guild: guild object that we want to check in
        userID: id for the user
        minimum: bool for if the user needs to be admin or higher.
        '''
        member = guild.get_member(userID)
        if member:
            if member.guild_permissions.manage_guild or self.check_member_in_list(guild, member, self.admin_roles):
                return True
        return False

    def is_mod(self, guild, userID, minimum:bool = False):
        '''checks if user with given userID is a mod in the given guild. Member either has ban members permission or
        a role that is considered a mod in this server
        
        guild: guild object that we want to check in
        userID: id for the user
        minimum: bool for if the user needs to be mod or higher. ie want being considered admin to return true
        '''
        member = guild.get_member(userID)
        if member:
            if member.guild_permissions.ban_members or self.check_member_in_list(guild, member, self.mod_roles) or\
                (minimum and self.is_admin(guild,userID,minimum)):
                return True
        return False
            
    def is_trusted(self, guild, userID, minimum:bool = False):
        '''checks if given userID is trusted in the given guild. Member has to have a role that is considered trusted
        
        guild: guild object that we want to check in
        userID: id for the user
        minimum: bool for if the user needs to be trusted or higher. ie want being considered mod or admin to return true
        '''
        member = guild.get_member(userID)
        if member:
            if (self.check_member_in_list(guild,member, self.trusted_roles) or (minimum and self.is_mod(guild,userID,minimum))):
                return True
        return False

    async def cog_check(self, ctx):
        # Minimum permission for all permissions commands: manage_server
        if ctx.guild:
            if self.is_admin(ctx.guild,ctx.author.id):
                return True
        if await self.bot.permission_manage_bot(ctx):
            return True
        return False

    @commands.group(name="permission_config", aliases=["permission", "permissions"], invoke_without_command=True)
    @commands.guild_only()
    async def permission_config(self, ctx):
        '''configure permissions for this server'''
        #this command displays server permissions if no subcommands called
        #TODO: protecting this against discord embed text limits
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
        #empty set will cause join to return empty string. display no_roles_string in that case
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
        '''reloads permissions from db'''
        await self.startup_cleanup()
        await ctx.send("reloaded permissions from db...")
        await ctx.invoke(self.permission_config)

    async def add_role(self, ctx, role: Role, local_list, db_model):
        '''adds given role to given local list and database table
        role: discord role to add
        local_list: the dictionary that is the permission level we want to add to
        db_model: ORM model for the table that stores list'''
        # role has to be a vaild role in this server
        guildid = ctx.guild.id
        if role.id in local_list[guildid]:
            # if role already here, then it has to be in db because that's where we fetched from
            await ctx.send("role already there!")
            return
        local_list[guildid].add(role.id)
        guild_row = Guild.get_or_create(serverid=guildid)[0]
        role_row = db_model.create(guild=guild_row, roleid=role.id)
        await ctx.send(f"role added!")
        # duplicates shouldn't be added as long as local cache and db are in sync

    @permission_config.command()
    @commands.guild_only()
    async def add_trusted_role(self, ctx, role: Role):
        '''add a role to trusted roles list for this guild'''
        await self.add_role(ctx, role, self.trusted_roles, TrustedRole)

    @permission_config.command()
    @commands.guild_only()
    async def add_mod_role(self, ctx, role: Role):
        '''add a role to mod roles list for this guild'''
        await self.add_role(ctx, role, self.mod_roles, ModRole)

    @permission_config.command()
    @commands.guild_only()
    async def add_admin_role(self, ctx, role: Role):
        '''add a role to trusted_roles list for this guild'''
        await self.add_role(ctx, role, self.admin_roles, AdminRole)

    @permission_config.command()
    async def add_bot_admin(self, ctx, user:User):
        '''add a user as a bot admin'''
        if user.id in self.bot_admin:
            await ctx.send(f"user already is in list")
            return
        self.bot_admin.add(user.id)
        BotAdmin.create(userid = user.id)
        await ctx.send("bot admin added")

    async def remove_role(self, ctx, role: Role, local_list, db_model):
        '''removes given role from given local list and database table
        role: discord role to remove
        local_list: the dictionary that is the permission level we want to remove from
        db_model: ORM model for the table that stores list'''
        guildid = ctx.guild.id
        if not role.id in local_list[guildid]:
            await ctx.send("role not there!")
            return
        try:
            local_list[guildid].discard(role.id)
            guild_row = Guild.get_or_create(serverid=guildid)[0]
            role_row = db_model.get(guild=guild_row, roleid=role.id)
            role_row.delete_instance()
            await ctx.send(f"role removed!")
        except Exception as e: # get can throw a DoesNotExist exception
            await ctx.send("removing failed")
    # see todos for add_role

    @permission_config.command()
    @commands.guild_only()
    async def remove_trusted_role(self, ctx, role: Role):
        '''remove a role from trusted roles list for this guild'''
        await self.remove_role(ctx,role,self.trusted_roles,TrustedRole)

    @permission_config.command()
    @commands.guild_only()
    async def remove_mod_role(self, ctx, role: Role):
        '''remove a role from mod roles list for this guild'''
        await self.remove_role(ctx, role, self.mod_roles, ModRole)

    @permission_config.command()
    @commands.guild_only()
    async def remove_admin_role(self, ctx, role: Role):
        '''remove a role from admin roles list for this guild'''
        await self.remove_role(ctx, role, self.admin_roles, AdminRole)

    @permission_config.command()
    async def remove_bot_admin(self, ctx, user:User):
        '''remove a Discord user from bot admin'''
        if user.id not in self.bot_admin:
            await ctx.send(f"user not found")
            return
        try:
            query = BotAdmin.delete().where(BotAdmin.userid==user.id)
            query.execute()
            self.bot_admin.discard(user.id)
            await ctx.send("bot admin removed")
        except Exception as e:
            await ctx.send("removing failed")

    @permission_config.command(
        brief="set an override to allow or deny a user a command in this server",
        help="must specify a member of this server, a valid command name, and True/1 or False/0 to set override to.",
        aliases=["add_command_override"])
    @commands.guild_only()
    async def set_command_override(self, ctx, member:Member, command_name, override:bool):
        '''
        set an override to allow or deny a user a command in this server
        '''
        
        async def add_override():
            try:
                guild_row = Guild.get_or_create(serverid=ctx.guild.id)[0]
                UserPermission.create(guild = guild_row, userid = member.id, command=command_name, allow=override)
                print("added to DB")
                if member.id not in self.command_permissions[ctx.guild.id]:
                    self.command_permissions[ctx.guild.id][member.id] = dict()
                self.command_permissions[ctx.guild.id][member.id].update({command_name:override})
                print("added to cache")
                await ctx.send(f"command override for {member.display_name} {command_name} set to {override}")
            except Exception as e:
                await ctx.send(f"failed to set override")
                await Utils.handle_exception("failed to add new override", self.bot, e)

        #TODO: add validation: command is valid command name
        if ctx.guild.id not in self.command_permissions:
            self.command_permissions[ctx.guild.id] = dict()
        if member.id in self.command_permissions[ctx.guild.id]:
            if command_name in self.command_permissions[ctx.guild.id][member.id]:
                # have an existing setting for this override
                try:
                    guild_row = Guild.get_or_create(serverid=ctx.guild.id)[0]
                    perm = UserPermission.get(UserPermission.guild == guild_row, UserPermission.userid == member.id, UserPermission.command==command_name)
                    perm.allow = override
                    perm.save()
                    self.command_permissions[ctx.guild.id][member.id][command_name] = override
                    await ctx.send(f"command override for {member.display_name} {command_name} set to {override}")
                except Exception as e:
                    await ctx.send(f"failed to set override")
                    await Utils.handle_exception("failed to edit override", self.bot, e)
            else:
                # haven't recorded any overrides for this command
                await add_override()
        else:
            # haven't recorded any overrides for this member
            await add_override()
        print("end of set command override", self.command_permissions[ctx.guild.id][member.id])

    @permission_config.command()
    @commands.guild_only()
    async def remove_command_override(self, ctx, member:Member, command_name):
        '''
        removes override. member goes back to permissions based on roles
        '''
        if ctx.guild.id not in self.command_permissions or len(self.command_permissions[ctx.guild.id]) == 0:
            await ctx.send(f"No overrides for the server!")
        elif member.id not in self.command_permissions[ctx.guild.id]:
            await ctx.send(f"no overrides for this member!")
        elif command_name not in self.command_permissions[ctx.guild.id][member.id]:
            await ctx.send(f"no overrides for this member and command!")
        else:
            # all info exists in maps, so must be a complete DB row of info that we need to remove. One row per override.
            try:
                guild_row = Guild.get_or_create(serverid=ctx.guild.id)[0]
                query = UserPermission.delete().where(UserPermission.guild == guild_row, UserPermission.userid == member.id, UserPermission.command==command_name)
                query.execute()
                self.command_permissions[ctx.guild.id][member.id].pop(command_name)
                await ctx.send(f"removed override for {member.display_name} {command_name}")
            except Exception as e:
                await Utils.handle_exception("failed to remove override", self.bot, e)
                await ctx.send(f"failed to remove override")

    # TODO: method for checking if user has permission that accepts ctx with command info?

def setup(bot):
    bot.add_cog(PermissionConfig(bot))
