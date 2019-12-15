import json
from collections import namedtuple

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
        help = f"""
        channel_config help
          - `![channel_config|chanconf] reload`
          - `![channel_config|chanconf] set channel_name channel_id` 
        """
        await ctx.send(help)

    @channel_config.command()
    @commands.is_owner()
    @commands.guild_only()
    async def reload(self, ctx: commands.Context):
        await self.startup_cleanup()
        await ctx.send("reloaded channel configs\n" + Utils.get_chanconf_description(self.bot, ctx.guild.id))

    @channel_config.command()
    @commands.guild_only()
    async def set(self, ctx, channel_name: str = "", channel_id: int = 0):
        if not validate_channel_name(channel_name) or channel_id == 0:
            await ctx.send(f"`channel set` requires both config channel [{Utils.welcome_channel}|{Utils.rules_channel}|{Utils.log_channel}] and channel_id")
            return
        channel_added = await self.set_channel(ctx, channel_name, channel_id)
        if channel_added:
            message = Lang.get_string('channel_config/channel_set', channel_name=channel_name, channel_id=channel_id)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {message}")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('BUG')} Failed")

    async def set_channel(self, ctx: commands.Context, channel_name: str, channel_id: int = 0):
        try:
            # Validate channel
            if ctx.guild.get_channel(channel_id) is None:
                return False

            row: ConfigChannel = ConfigChannel.get_or_none(serverid=ctx.guild.id, configname=channel_name)
            if row is None:
                ConfigChannel.create(serverid=ctx.guild.id, channelid=str(channel_id), configname=channel_name)
            else:
                row.channelid = channel_id
                row.save()
            self.bot.config_channels[ctx.guild.id][channel_name] = channel_id
            return True
        except Exception as ex:
            return False


def setup(bot):
    bot.add_cog(ChannelConfig(bot))
