from discord import Message
from discord.ext import commands
from discord.ext.commands import Context, command

from cogs.BaseCog import BaseCog
from utils import Configuration, Logging


class Welcomer(BaseCog):
    @command()
    async def welcome(self, ctx: Context):
        """welcomer_help"""
        txt = Configuration.get_var("welcome_msg")
        Logging.info(ctx)
        rules = self.bot.get_channel(Configuration.get_var('rules_channel'))
        await ctx.send(txt.format(ctx.author.mention, rules.mention))

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        print(message)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel = member.guild.system_channel
        txt = Configuration.get_var("welcome_msg")
        rules_channel = self.bot.get_channel(Configuration.get_var('rules_channel'))
        welcome_channel = self.bot.get_channel(Configuration.get_var('welcome_channel'))
        txt = txt.format(member.mention, rules_channel.mention)
        Logging.info(txt)
        if welcome_channel is not None:
            await welcome_channel.send(txt)


def setup(bot):
    bot.add_cog(Welcomer(bot))
