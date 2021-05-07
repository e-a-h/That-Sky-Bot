import discord
from discord import Role, TextChannel, Message
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Configuration, Utils, Lang
from utils.Database import Guild


class GuildConfig(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        for guild in self.bot.guilds:
            self.init_guild(guild)

    def init_guild(self, guild):
        row = Guild.get_or_create(serverid=guild.id)[0]
        Utils.GUILD_CONFIGS[guild.id] = row
        return row

    def cog_unload(self):
        pass

    async def cog_check(self, ctx):
        if ctx.guild is None:
            return False
        return ctx.author.guild_permissions.ban_members

    def get_guild_config(self, guild_id):
        if guild_id in Utils.GUILD_CONFIGS:
            return Utils.GUILD_CONFIGS[guild_id]
        return self.init_guild(guild_id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del Utils.GUILD_CONFIGS[guild.id]
        # keep guild record and clear channel configs and default lang
        guild_row = Guild.get(serverid=guild.id)
        guild_row.memberrole = 0
        guild_row.nonmemberrole = 0
        guild_row.mutedrole = 0
        guild_row.betarole = 0
        guild_row.welcomechannelid = 0
        guild_row.ruleschannelid = 0
        guild_row.logchannelid = 0
        guild_row.entrychannelid = 0
        guild_row.maintenancechannelid = 0
        guild_row.rulesreactmessageid = 0
        guild_row.defaultlocale = ''
        guild_row.save()

    @commands.group(name="guildconfig",
                    aliases=['guild', 'guildconf'],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def guild_config(self, ctx: commands.Context):
        """
        List the guild settings
        """
        my_guild = Utils.GUILD_CONFIGS[ctx.guild.id]
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=Utils.COLOR_LIME,
            title=Lang.get_locale_string("guild_config/info_title", ctx, server_name=ctx.guild.name))

        role_description = "none"
        if my_guild.memberrole:
            role = ctx.guild.get_role(my_guild.memberrole)
            role_description = f"{role.name} ({role.id})"
        embed.add_field(name="Member Role", value=role_description)

        role_description = "none"
        if my_guild.nonmemberrole:
            role = ctx.guild.get_role(my_guild.nonmemberrole)
            role_description = f"{role.name} ({role.id})"
        embed.add_field(name="Nonmember Role", value=role_description)

        role_description = "none"
        if my_guild.mutedrole:
            role = ctx.guild.get_role(my_guild.mutedrole)
            role_description = f"{role.name} ({role.id})"
        embed.add_field(name="Muted Role", value=role_description)

        role_description = "none"
        if my_guild.betarole:
            role = ctx.guild.get_role(my_guild.betarole)
            role_description = f"{role.name} ({role.id})"
        embed.add_field(name="Beta Role", value=role_description)

        channel_description = "none"
        if my_guild.welcomechannelid:
            channel = ctx.guild.get_channel(my_guild.welcomechannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Welcome Channel", value=channel_description)

        channel_description = "none"
        if my_guild.ruleschannelid:
            channel = ctx.guild.get_channel(my_guild.ruleschannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Rules Channel", value=channel_description)

        channel_description = "none"
        if my_guild.logchannelid:
            channel = ctx.guild.get_channel(my_guild.logchannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Log Channel", value=channel_description)

        channel_description = "none"
        if my_guild.entrychannelid:
            channel = ctx.guild.get_channel(my_guild.entrychannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Entry Channel", value=channel_description)

        channel_description = "none"
        if my_guild.maintenancechannelid:
            channel = ctx.guild.get_channel(my_guild.maintenancechannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Maintenance Channel", value=channel_description)

        rules_id = my_guild.rulesreactmessageid if my_guild.rulesreactmessageid else 'none'
        embed.add_field(name="Rules React Message ID", value=rules_id)

        locale = my_guild.defaultlocale if my_guild.defaultlocale else 'none'
        embed.add_field(name="Default Locale", value=locale)

        await ctx.send(embed=embed)

    async def set_field(self, ctx, field, val):
        my_guild = Utils.GUILD_CONFIGS[ctx.guild.id]
        try:
            setattr(my_guild, field, val.id)
            my_guild.save()
            self.init_guild(ctx.guild)
            await ctx.send(f"Ok! `{field}` is now `{val.name} ({val.id})`")
        except Exception as e:
            await ctx.send(f"I failed to set `{field}` value to `{val.name} ({val.id})`")

    @guild_config.group(invoke_without_command=False)
    @commands.guild_only()
    async def set(self, ctx: commands.Context):
        """
        Set one of the base settings for Skybot in this guild
        """
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @set.command(aliases=['member', 'memberrole'])
    @commands.guild_only()
    async def member_role(self, ctx, role: Role):
        """
        Set the member role

        Used in cogs that read/set/unset the membership role in this server
        role: Role name or role id
        """
        await self.set_field(ctx, 'memberrole', role)

    @set.command(aliases=['nonmember', 'nonmemberrole'])
    @commands.guild_only()
    async def nonmember_role(self, ctx, role: Role):
        """
        Set the nonmember role

        Used in cogs that read/set/unset the nonmember role in this server
        role: Role name or role id
        """
        await self.set_field(ctx, 'nonmemberrole', role)

    @set.command(aliases=['muted', 'mutedrole'])
    @commands.guild_only()
    async def muted_role(self, ctx, role: Role):
        """
        Set the muted role

        Used in cogs that read/set/unset the muted role in this server
        role: Role name or role id
        """
        await self.set_field(ctx, 'mutedrole', role)

    @set.command(aliases=['beta', 'betarole'])
    @commands.guild_only()
    async def beta_role(self, ctx, role: Role):
        """
        Set the beta role

        Used in cogs that read/set/unset the beta role in this server
        role: Role name or role id
        """
        await self.set_field(ctx, 'betarole', role)

    @set.command(aliases=['welcome', 'welcomechannel'])
    @commands.guild_only()
    async def welcome_channel(self, ctx, chan: TextChannel):
        """
        Set the welcome channel

        Used in cogs that read/set/unset the welcome channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'welcomechannelid', chan)

    @set.command(aliases=['rules', 'ruleschannel'])
    @commands.guild_only()
    async def rules_channel(self, ctx, chan: TextChannel):
        """
        Set the rules channel

        Used in cogs that read/set/unset the rules channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'ruleschannelid', chan)

    @set.command(aliases=['log', 'logchannel'])
    @commands.guild_only()
    async def log_channel(self, ctx, chan: TextChannel):
        """
        Set the log channel

        Used in cogs that read/set/unset the log channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'logchannelid', chan)

    @set.command(aliases=['entry', 'entrychannel'])
    @commands.guild_only()
    async def entry_channel(self, ctx, chan: TextChannel):
        """
        Set the entry channel

        Used in cogs that read/set/unset the entry channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'entrychannelid', chan)

    @set.command(aliases=['maintenance', 'maintenancechannel'])
    @commands.guild_only()
    async def maintenance_channel(self, ctx, chan: TextChannel):
        """
        Set the maintenance channel

        Used in cogs that read/set/unset the maintenance channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'maintenancechannelid', chan)

    @set.command(aliases=['rulesmessage', 'rulesreactmessage'])
    @commands.guild_only()
    async def rules_react_message(self, ctx, msg: Message):
        """
        Set the rules react message id

        Used in cogs that read/set/unset the rulesreactmessageid in this server
        role: chanelid-messageid, messageid, or url
        """
        my_guild = Utils.GUILD_CONFIGS[ctx.guild.id]
        try:
            my_guild.rulesreactmessageid = msg.id
            my_guild.save()
            self.init_guild(ctx.guild)
            await ctx.send(f"Ok! `rulesreactmessageid` is now `{msg.id}`")
        except Exception as e:
            await ctx.send(f"I failed to set `rulesreactmessageid` value to `{msg.id}`")


def setup(bot):
    bot.add_cog(GuildConfig(bot))
