from discord import Message, Member, client
from discord.ext import commands
from discord.ext.commands import Context

from cogs.BaseCog import BaseCog
from utils import Configuration, Logging


class Welcomer(BaseCog):
    async def welcome(self, ctx: Context):
        """welcomer_help"""
        txt = Configuration.get_var("welcome_msg")
        Logging.info(ctx)
        await ctx.send(txt.format(ctx.author.mention))

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        print(message)

    @commands.Cog.listener()
    async def on_member_join(member: Member):
        message = "it looks like {} has joined".format(member.mention)
        Logging.info(message)


def setup(bot):
    bot.add_cog(Welcomer(bot))
