import json
from collections import namedtuple

import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from sky import Skybot
from utils import Configuration, Logging, Emoji, Lang
from utils.Database import ConfigChannel
from utils.Utils import validate_channel_name
from utils import Utils


class ChannelConfig(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        # Load channels
        self.bot.config_channels = dict()
        for guild in self.bot.guilds:
            my_channels = dict()
            for row in ConfigChannel.select().where(ConfigChannel.serverid == guild.id):
                if validate_channel_name(row.configname):
                    my_channels[row.configname] = row.channelid
                else:
                    Logging.error(f"Misconfiguration in config channel: {row.configname}")
            self.bot.config_channels[guild.id] = my_channels

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.bot.config_channels[guild.id] = dict()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.bot.config_channels[guild.id]
        for row in ConfigChannel.select().where(ConfigChannel.serverid == guild.id):
            row.delete_instance()

    def cog_check(self, ctx):
        return ctx.bot.is_owner(ctx.author) or ctx.author.id in Configuration.get_var("ADMINS", [])

    @commands.group(name="channel_config", aliases=["chanconf", "channelconfig"], invoke_without_command=True)
    @commands.guild_only()
    async def channel_config(self, ctx):
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_string("channel_config/info", server_name=ctx.guild.name))
        embed.add_field(name='Commands', value=Lang.get_string("channel_config/commands"), inline=False)
        embed.add_field(name='Configurable Channels',
                        value=f"[{Utils.welcome_channel}|{Utils.rules_channel}|"
                              f"{Utils.log_channel}|{Utils.ro_art_channel}|{Utils.entry_channel}]",
                        inline=False)

        for row in ConfigChannel.select().where(ConfigChannel.serverid == ctx.guild.id):
            embed.add_field(name=row.configname, value=f"<#{row.channelid}>", inline=False)
        await ctx.send(embed=embed)

    @channel_config.command()
    @commands.is_owner()
    @commands.guild_only()
    async def reload(self, ctx: commands.Context):
        await self.startup_cleanup()
        await ctx.send("reloaded channel configs\n" + Utils.get_chanconf_description(self.bot, ctx.guild.id))

    @channel_config.command()
    @commands.guild_only()
    async def set(self, ctx, channel_name: str = "", channel_id: int = 0):
        if not validate_channel_name(channel_name):
            await ctx.send(f"""
`channel set` requires both config channel name and channel_id.
`[{Utils.ro_art_channel}|{Utils.welcome_channel}|{Utils.rules_channel}|{Utils.log_channel}|{Utils.entry_channel}]`
""")
            return
        channel_added = await self.set_channel(ctx, channel_name, channel_id)
        if channel_added:
            message = Lang.get_string('channel_config/channel_set', channel_name=channel_name, channel_id=channel_id)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {message}")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('BUG')} Failed")

    async def set_channel(self, ctx: commands.Context, channel_name: str, channel_id: int = 0):
        # Validate channel
        if channel_id != 0 and ctx.guild.get_channel(channel_id) is None:
            return False

        row: ConfigChannel = ConfigChannel.get_or_create(serverid=ctx.guild.id, configname=channel_name)[0]
        row.channelid = channel_id
        row.save()
        self.bot.config_channels[ctx.guild.id][channel_name] = channel_id
        return True


def setup(bot):
    bot.add_cog(ChannelConfig(bot))
