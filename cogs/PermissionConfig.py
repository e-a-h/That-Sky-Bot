import discord
from discord import Role, User, Member
from discord import guild
from discord import AllowedMentions
from discord.ext import commands

from cogs.BaseCog import BaseCog
import sky
from utils import Lang
from utils.Database import Guild, BotAdmin, TrustedRole, AdminRole, ModRole, UserPermission
from utils import Utils

#TODO: better perms around bot admin, shouldn't be able to change server settings and stuff?
#TODO: command names a bit confusing even with aliases. is there any better?
#TODO: enhancement, command override validator that checks if command overrides are redundant or not. Or cleaning out nonexistant commands
#TODO: protecting permission list display against discord embed text limits
class PermissionConfig(BaseCog):
    '''cog for managing permissions via roles and specific command overrides. 
    This cog provides server admins commands to add and remove roles or overrides to control permissions,
    as well as providing admins of the bot itself commands to easily add/remove bot admin user accounts. 
    Roles are sorted into three levels of trust: trusted, mod and admins. 
    A user is considered a, for example, mod in the server by the cog if they have a role that is listed as a mod role, 
    regardless if they have server permissions that are considered moderator permissions. 
    A seperate boolean allows you to control if you want higher trust roles to also be considered that level -
    i.e. mod and admin roles are considered trusted, admin roles considered mod - 
    without needing to add multiple roles to multiple users or lists.
    Overrides act per server per user per command combination, and are just a flag applied over any existing permissions.
    Developer info segment below.
    '''
    '''
    This cog contains helper methods for checking user permissions, which are limited to checking if user has role(s) or overrides
    as described above, and is only used as part of the full permissions check.
    The best home for the full check of overides on top of actual server permissions and role considerations is in the bot file. In cogs that need it, 
    please `import sky` and use the `check_command_permission` and `check_cog_permission_level` methods for checking permissions
    '''
    permission_levels = {2:"trusted",4:"mod",6:"admin"}

    def __init__(self, bot):
        super().__init__(bot)
        self.admin_roles = dict()
        '''dictionary of roles that bot considers admin per server
        
        server id int -> set(role id int)'''
        self.mod_roles = dict()
        '''dictionary of roles that bot considers moderator per server
        
        server id int -> set(role id int)'''
        self.trusted_roles = dict()
        '''dictionary of roles that bot considers trusted per server
        
        server id int -> set(role id int)'''
        self.command_permissions = dict()
        '''dictionary of information about permission overrides for using commands per server per user per command
        
        server id int -> user id int -> command name string -> permission boolean'''
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        '''load info for permissions for all guilds bot is in, and list of bot admins'''
        self.bot.bot_admins = set()
        for row in BotAdmin.select():
            self.bot.bot_admins.add(row.userid)
        for guild in self.bot.guilds:
            self.init_guild(guild)
            self.load_guild(guild)

    def init_guild(self, guild):
        '''initializes maps to hold admin, mod and trusted roles and command overrides for this guild

        Parameters
        -----
        guild: `Guild`
            guild object to initialize memory for'''
        self.admin_roles[guild.id] = set()
        self.mod_roles[guild.id] = set()
        self.trusted_roles[guild.id] = set()
        self.command_permissions[guild.id] = dict()

    def load_guild(self, guild):
        '''load from database all admin, mod, and trusted roles, and command overrides for given guild. When loading, if bot can't find the role or member
        in the guild, it deletes the row from DB. It also looks through command overrides and if any command names match registered commands' aliases
        it changes it to qualified names
        
        Parameters
        -----
        guild: `Guild`
            guild object that we want to load role info for.
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
            matched_command = self.bot.get_command(row.command)
            if matched_command:
                row.command = matched_command.qualified_name
                row.save()
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
        '''listner for when blot leaves guild. delete guild info from memory and database'''
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

    def check_member_in_list(self, member, local_list):
        '''helper method for checking if given member has a role in the given list for the given guild. 
        guild is included in a Member object. Does not account for command overrides. see `has_permission_override`

        Parameters
        -----
        member: `Member`
           guild member object that we want to check
        local_list: `dict`
            one of the dictionaries of this cog: `admin_roles`, `mod_roles`, `trusted_roles`. 
        
        Return
        -----
        whether or not member has a role in list
        '''
        if member:
            if member.guild.id not in local_list:
                return False
            for role in member.roles:
                    if role.id in local_list[member.guild.id]:
                        return True
        return False

    def is_server_admin(self, guild, userID, minimum:bool = False):
        '''checks if user with given userID has a role that is listed as admin in the given guild
        Does not account for command overrides. see `has_permission_override`

        Parameters
        -----
        guild: `Guild`
            guild that we want to check in
        userID: `int`
            id for the user
        minimum: `bool`
            whether to return true if user has a role that is considered higher than admin but not admin (none at the moment)

        Return
        -----
        `bool` if user has admin role, or higher if asked for
        '''
        if guild == None:
            return False
        return self.check_member_in_list(guild.get_member(userID), self.admin_roles)

    def is_server_mod(self, guild, userID, minimum:bool = False):
        '''checks if user with given userID has a role that is listed as a mod in the given guild.
        Does not account for command overrides. see `has_permission_override`
        
        Parameters
        -----
        guild: `Guild`
            guild that we want to check in
        userID: `int`
            id for the user
        minimum: `bool`
            whether to return true if user has a role that is considered higher than mod but not mod (i.e. admin)

        Return
        -----
        `bool` if user has mod role, or higher if asked for
        '''
        if guild == None:
            return False
        return self.check_member_in_list(guild.get_member(userID), self.mod_roles) or (minimum and self.is_server_admin(guild,userID,minimum))
            
    def is_server_trusted(self, guild, userID, minimum:bool = False):
        '''checks if given userID has a role that is listed as trusted in the given guild. 
        Does not account for command overrides. see `has_permission_override`
        
        Parameters
        -----
        guild: `Guild`
            guild that we want to check in
        userID: `int`
            id for the user
        minimum: `bool`
            whether to return true if user has a role that is considered higher than trusted but not trusted (i.e. mod or admin)

        Return
        -----
        `bool` if user has trusted role, or higher if asked for
        '''
        if guild == None:
            return False
        return self.check_member_in_list(guild.get_member(userID), self.trusted_roles) or (minimum and self.is_server_mod(guild,userID,minimum))
    
    def has_permission_override(self,ctx):
        '''checks if member has permission to run the command they are trying according to command overrides
        
        Parameters
        -----
        ctx `commands.Context`
            context command is being run in

        Return
        -----
        `None` or `bool` what the override is set to or None if not found
        '''
        if ctx.guild.id not in self.command_permissions or ctx.author.id not in self.command_permissions[ctx.guild.id] or\
             ctx.command.qualified_name not in self.command_permissions[ctx.guild.id][ctx.author.id]:
             # not all keys present so there isn't an entry for requested command override.
            return None
        return self.command_permissions[ctx.guild.id][ctx.author.id][ctx.command.qualified_name]

    async def cog_check(self, ctx):
        # must be considered a server admin or bot admin to use/manage this cog
        if ctx.guild:
            if sky.check_command_permission(ctx, "admin_role", True):
                return True
        if await self.bot.permission_manage_bot(ctx):
            return True
        return False

    @commands.group(name="permission_config", aliases=["perms", "permissions"], invoke_without_command=True)
    @commands.guild_only()
    async def permission_config(self, ctx):
        '''configure permissions for this server'''
        #this command displays server permissions if no subcommands called
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

        no_roles_string = Lang.get_locale_string("permission_config/no_roles_set", ctx)
        # empty set will cause join to return empty string. display no_roles_string in that case
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
        '''reloads all permission information'''
        await self.startup_cleanup()
        await ctx.send(Lang.get_locale_string("permission_config/reloaded", ctx))
        await ctx.invoke(self.permission_config)

    async def add_role(self, ctx, role: Role, permission_level, db_model):
        '''helper method that adds given role to one of the role lists and database table

        Parameters
        -----
        role: `Role`
            discord role object that you want to add
        permission_level: `string`
            one of the strings of `self.permission_levels`, specifies which dictionary to use
        db_model: `peewee.Model`
            ORM model for the table that stores list
        '''
        display_name = "the list"
        local_list = self.trusted_roles
        if permission_level == self.permission_levels[2]:
            display_name = "trusted roles"
        elif permission_level == self.permission_levels[4]:
            local_list = self.mod_roles
            display_name = "mod roles"
        elif permission_level == self.permission_levels[6]:
            local_list = self.admin_roles
            display_name = "admin roles"

        guildid = ctx.guild.id
        # role has to be a vaild role in the guild command was executed in. prevents affecting other guilds
        if role.guild.id != ctx.guild.id:
            fail_message = Lang.get_locale_string("permission_config/failed_add", ctx, role=role.mention, list=display_name)
            fail_reason = Lang.get_locale_string("permission_config/fail_reason_invalid", ctx, role=role.mention)
            await ctx.send(content=f"{fail_message} {fail_reason}", allowed_mentions=AllowedMentions.none())
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("permission_config/info", ctx, server_name=ctx.guild.name))
        no_roles_string = Lang.get_locale_string("permission_config/no_roles_set", ctx)
        if role.id in local_list[guildid]:
            # if role already here, then it has to be in db because that's where we fetched from
            print("list",local_list, "filtered",[i for i in local_list if ctx.guild.get_role(i) != None])
            embed.add_field(name=display_name, value='\n'.join([ctx.guild.get_role(i).mention for i in local_list[guildid] if ctx.guild.get_role(i) != None]) if len(local_list[guildid]) > 0 else no_roles_string, inline=False)
            await ctx.send(content=Lang.get_locale_string("permission_config/add_duplicate", ctx, role=role.mention, list=display_name), embed=embed, allowed_mentions=AllowedMentions.none())
            return
        local_list[guildid].add(role.id)
        try:
            guild_row = Guild.get_or_create(serverid=guildid)[0]
            role_row = db_model.create(guild=guild_row, roleid=role.id)
        except Exception as e:
            self.init_guild(ctx.guild)
            self.load_guild(ctx.guild)
        embed.add_field(name=display_name, value='\n'.join([ctx.guild.get_role(i).mention for i in local_list[guildid] if ctx.guild.get_role(i) != None]) if len(local_list[guildid]) > 0 else no_roles_string, inline=False)
        await ctx.send(content=Lang.get_locale_string("permission_config/added", ctx, role=role.mention, list=display_name), embed=embed, allowed_mentions=AllowedMentions.none())
        # duplicates shouldn't be added as long as local cache and db are in sync, or using unique index on the tables

    @permission_config.command(aliases=["add_trusted", "a_trusted"])
    @commands.guild_only()
    async def add_trusted_role(self, ctx, role: Role):
        '''add a role to trusted roles list for this guild'''
        await self.add_role(ctx, role, self.permission_levels[2], TrustedRole)

    @permission_config.command(aliases=["add_mod", "a_mod"])
    @commands.guild_only()
    async def add_mod_role(self, ctx, role: Role):
        '''add a role to mod roles list for this guild'''
        await self.add_role(ctx, role, self.permission_levels[4], ModRole)

    @permission_config.command(aliases=["add_admin", "a_admin"])
    @commands.guild_only()
    async def add_admin_role(self, ctx, role: Role):
        '''add a role to admin list for this guild'''
        await self.add_role(ctx, role, self.permission_levels[6], AdminRole)

    @permission_config.command(aliases=["a_bot_admin"])
    @sky.can_admin_bot()
    async def add_bot_admin(self, ctx, user:User):
        '''add a user as a bot admin. only usable by current bot admins'''
        if user.id in self.bot.bot_admins:
            await ctx.send(content=Lang.get_locale_string("permission_config/add_duplicate", ctx, role=user.mention, list="bot admin list"),allowed_mentions=AllowedMentions.none())
            return
        self.bot.bot_admins.add(user.id)
        try:
            BotAdmin.create(userid = user.id)
        except Exception as e:
            self.bot.bot_admins = set()
            for row in BotAdmin.select():
                self.bot.bot_admins.add(row.userid)
        await ctx.send(content=Lang.get_locale_string("permission_config/added", ctx, role=user.mention, list="bot admin list"),allowed_mentions=AllowedMentions.none())

    async def remove_role(self, ctx, role: Role, permission_level, db_model):
        '''removes given role from given local list and database table

        Parameters
        -----
        role: `Role`
            discord role to remove
        permission_level: `string`
            one of the strings of `self.permission_levels`, specifies which dictioanry to use
        db_model: `peewee.Model`
            ORM model for the table that stores list
        '''
        display_name = "the list"
        local_list = self.trusted_roles
        if permission_level == self.permission_levels[2]:
            display_name = "trusted roles"
        elif permission_level == self.permission_levels[4]:
            local_list = self.mod_roles
            display_name = "mod roles"
        elif permission_level == self.permission_levels[6]:
            local_list = self.admin_roles
            display_name = "admin roles"
        guildid = ctx.guild.id
        # role has to be a vaild role in the guild command was executed in. prevents affecting other guilds
        if role.guild.id != ctx.guild.id:
            fail_message = Lang.get_locale_string("permission_config/failed_remove", ctx, role=role.mention, list=display_name)
            fail_reason = Lang.get_locale_string("permission_config/fail_reason_invalid", ctx, role=role.mention)
            await ctx.send(content=f"{fail_message} {fail_reason}", allowed_mentions=AllowedMentions.none())
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("permission_config/info", ctx, server_name=ctx.guild.name))
        no_roles_string = Lang.get_locale_string("permission_config/no_roles_set", ctx)

        if not role.id in local_list[guildid]:
            embed.add_field(name=display_name, value='\n'.join([ctx.guild.get_role(i).mention for i in local_list[guildid] if ctx.guild.get_role(i) != None]) if len(local_list[guildid]) > 0 else no_roles_string, inline=False)
            await ctx.send(content=Lang.get_locale_string("permission_config/remove_missing", ctx, role=role.mention, list=display_name), embed=embed, allowed_mentions=AllowedMentions.none())
            return
        try:
            local_list[guildid].discard(role.id)
            guild_row = Guild.get_or_create(serverid=guildid)[0]
            db_model.delete().where(db_model.guild==guild_row, db_model.roleid==role.id).execute()
            embed.add_field(name=display_name, value='\n'.join([ctx.guild.get_role(i).mention for i in local_list[guildid] if ctx.guild.get_role(i) != None]) if len(local_list[guildid]) > 0 else no_roles_string, inline=False)
            await ctx.send(content=Lang.get_locale_string("permission_config/removed", ctx, role=role.mention, list=display_name), embed=embed, allowed_mentions=AllowedMentions.none())
        except Exception as e: # get can throw a DoesNotExist exception
            await Utils.handle_exception("encoutnered exception when removing role from permission list", self.bot, e)
            await ctx.send("removing failed")

    @permission_config.command(aliases=["remove_trusted", "r_trusted"])
    @commands.guild_only()
    async def remove_trusted_role(self, ctx, role: Role):
        '''remove a role from trusted roles list for this guild'''
        await self.remove_role(ctx, role, self.permission_levels[2], TrustedRole)

    @permission_config.command(aliases=["remove_mod", "r_mod"])
    @commands.guild_only()
    async def remove_mod_role(self, ctx, role: Role):
        '''remove a role from mod roles list for this guild'''
        await self.remove_role(ctx, role, self.permission_levels[4], ModRole)

    @permission_config.command(aliases=["remove_admin", "r_admin"])
    @commands.guild_only()
    async def remove_admin_role(self, ctx, role: Role):
        '''remove a role from admin roles list for this guild'''
        await self.remove_role(ctx, role, self.permission_levels[6], AdminRole)

    @permission_config.command(aliases=["r_bot_admin"])
    @sky.can_admin_bot()
    async def remove_bot_admin(self, ctx, user:User):
        '''remove a Discord user from bot admin. only usable by current bot admins'''
        if user.id not in self.bot.bot_admins:
            await ctx.send(content=Lang.get_locale_string("permission_config/remove_missing", ctx, role=user.mention, list="bot admin list"), allowed_mentions=AllowedMentions.none())
            return
        try:
            query = BotAdmin.delete().where(BotAdmin.userid==user.id)
            query.execute()
            self.bot.bot_admins.discard(user.id)
            await ctx.send(content=Lang.get_locale_string("permission_config/removed", ctx, role=user.mention, list="bot admin list"), allowed_mentions=AllowedMentions.none())
        except Exception as e:
            await Utils.handle_exception("encountered exception trying to remove bot admin", self.bot, e)
            await ctx.send("removing failed")

    @permission_config.command(
        brief="set an override to allow or deny a user a command in this server",
        help="must specify a member of this server, a command name, and True/1 or False/0 to set override to.",
        aliases=["set_command_override", "add_command", "set_command", "add_override","set_override", "a_command", "s_command", "a_override","s_override"])
    @commands.guild_only()
    async def add_command_override(self, ctx, member:Member, command_name, override:bool):
        '''
        set an override to allow/deny a user a command in this server. if command has multiple words, put it in quotes
        '''

        # need to massage command_name to be the official name so it's easier to find later
        # and should be able to add overrides for custom commands if they ever get role lock support. those aren't registered with bot. 
        matched_command = ctx.bot.get_command(command_name)
        register_status = Lang.get_locale_string("permission_config/unregisted_command", ctx)
        if matched_command:
            command_name = matched_command.qualified_name
            register_status = Lang.get_locale_string("permission_config/registed_command", ctx)

        guild_row = Guild.get_or_create(serverid=ctx.guild.id)[0]
        if ctx.guild.id not in self.command_permissions or \
                member.id not in self.command_permissions[ctx.guild.id] or \
                command_name not in self.command_permissions[ctx.guild.id][member.id]:
            # provided information not completely in memory, means new entry
            try:
                UserPermission.create(guild = guild_row, userid = member.id, command=command_name, allow=override)
                if ctx.guild.id not in self.command_permissions:
                    self.command_permissions[ctx.guild.id] = dict()
                if member.id not in self.command_permissions[ctx.guild.id]:
                    self.command_permissions[ctx.guild.id][member.id] = dict()
                self.command_permissions[ctx.guild.id][member.id].update({command_name:override})
                
                add_status = Lang.get_locale_string("permission_config/override_added", ctx, user=member.display_name, command=command_name, override=override)
                await ctx.send(content=f"{add_status}\n{register_status}", allowed_mentions=AllowedMentions.none())
            except Exception as e: # potentially a duplicate key exception
                await ctx.send(f"failed to add override")
                await Utils.handle_exception("failed to add override", self.bot, e)           
        else:
            # all info exists in maps, so must be a complete DB row of info already. not adding, setting override.
            try:
                perm = UserPermission.get(UserPermission.guild == guild_row, UserPermission.userid == member.id, UserPermission.command==command_name)
                perm.allow = override
                perm.save()
                self.command_permissions[ctx.guild.id][member.id][command_name] = override
                add_status = Lang.get_locale_string("permission_config/override_set", ctx, user=member.display_name, command=command_name, override=override)
                await ctx.send(content=f"{add_status}\n{register_status}", allowed_mentions=AllowedMentions.none())
            except Exception as e:
                await ctx.send(f"failed to set override")
                await Utils.handle_exception("failed to edit override", self.bot, e)

    @permission_config.command(aliases=["remove_command", "remove_override","r_override","r_command"])
    @commands.guild_only()
    async def remove_command_override(self, ctx, member:Member, command_name):
        '''
        removes override. member goes back to permissions based on roles in server
        '''
        matched_command = ctx.bot.get_command(command_name)
        if matched_command:
            command_name = matched_command.qualified_name

        if ctx.guild.id not in self.command_permissions or \
                member.id not in self.command_permissions[ctx.guild.id] or \
                command_name not in self.command_permissions[ctx.guild.id][member.id]:
            await ctx.send(Lang.get_locale_string("permission_config/override_missing", ctx))
        else:
            # all info exists in maps, so must be a complete DB row of info that we need to remove. One row per override.
            try:
                guild_row = Guild.get_or_create(serverid=ctx.guild.id)[0]
                query = UserPermission.delete().where(UserPermission.guild == guild_row, UserPermission.userid == member.id, UserPermission.command==command_name)
                query.execute()
                self.command_permissions[ctx.guild.id][member.id].pop(command_name)
                await ctx.send(content=Lang.get_locale_string("permission_config/override_removed", ctx, user=member.mention, command=command_name),allowed_mentions=AllowedMentions.none())
            except Exception as e:
                await Utils.handle_exception("failed to remove override", self.bot, e)
                await ctx.send(f"failed to remove override")

def setup(bot):
    bot.add_cog(PermissionConfig(bot))
