import discord
from discord.ext import commands, tasks

from cogs.BaseCog import BaseCog


class CogName(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.guild_specific_lists = dict()
        for guild in self.bot.guilds:
            self.init_guild(guild)
        self.periodic_task.start()

    def cog_unload(self):
        self.periodic_task.cancel()

    def init_guild(self, guild):
        # init guild-specific dicts and lists
        self.guild_specific_lists[guild.id] = []
        pass

    @tasks.loop(seconds=60)
    async def periodic_task(self):
        # periodic task to run while cog is loaded
        pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        # delete guild-specific dicts and lists, remove persistent vars, clean db
        del self.guild_specific_lists[guild.id]
        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # do something with messages
        pass


def setup(bot):
    bot.add_cog(CogName(bot))
