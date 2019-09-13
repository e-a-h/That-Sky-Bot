from discord import Message
from discord.ext import commands

from cogs.BaseCog import BaseCog


class Welcomer(BaseCog):
    @commands.Cog.listener()
    async def on_message(self, message: Message):
        print(message)


def setup(bot):
    bot.add_cog(Welcomer(bot))