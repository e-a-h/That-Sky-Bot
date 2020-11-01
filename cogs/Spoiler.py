import io

import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Utils


class Spoiler(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self.loaded = False
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        self.loaded = True

    @commands.command()
    @commands.guild_only()
    async def spoiler(self, ctx, *, content=""):
        msg = f"{ctx.author.mention} asked me to spoiler-tag this"
        file_list = []
        output = content.lstrip().rstrip()
        if ctx.message.attachments:
            for attachment in ctx.message.attachments:
                buffer = io.BytesIO()
                await attachment.save(buffer)
                file_list.append(discord.File(buffer, attachment.filename, spoiler=True))

        if output:
            txt = await Utils.clean(output, emoji=False)
            msg = f"{msg}: ||{txt}||"

        if file_list:
            await ctx.send(content=msg, files=file_list)
        elif output:
            await ctx.send(content=msg)

        await ctx.message.delete()

    @commands.command()
    @commands.guild_only()
    async def bubble_wrap(self, ctx, *, content=""):
        msg = ""
        for char in content:
            msg = f"{msg}||{char}||"

        await ctx.send(msg)
        await ctx.message.delete()


def setup(bot):
    bot.add_cog(Spoiler(bot))
