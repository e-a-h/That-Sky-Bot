import discord
from discord import client, Member
from discord.ext.commands import command, Context

from utils import Configuration, Logging

from cogs.BaseCog import BaseCog


class Welcomer(BaseCog):
    @command()
    async def welcome(self, ctx: Context):
        """welcomer_help"""
        txt = Configuration.get_var("welcome_msg")
        Logging.info(ctx)
        await ctx.send(txt.format(ctx.author.mention))

    c = discord.Client()

    @c.event
    async def on_member_join(member: Member):
        message = "it looks like {} has joined".format(member.mention)
        await client.send_message("general", message)


def setup(bot):
    bot.add_cog(Welcomer(bot))
