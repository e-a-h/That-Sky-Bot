import time

from discord.ext.commands import command, Context

from cogs.BaseCog import BaseCog
from utils import Utils


class Basic(BaseCog):

    async def cog_check(self, ctx):
        return Utils.permission_official_mute(ctx.author.id)

    @command(hidden=True)
    async def ping(self, ctx: Context):
        # if hasattr(ctx, 'locale'):
        #     print(ctx.locale)
        # else:
        #     print('no locale')
        """show ping times"""
        t1 = time.perf_counter()
        message = await ctx.send(":ping_pong:")
        t2 = time.perf_counter()
        rest = round((t2 - t1) * 1000)
        latency = round(self.bot.latency * 1000, 2)
        await message.edit(
            content=f":hourglass: REST API ping is {rest} ms | Websocket ping is {latency} ms :hourglass:")


def setup(bot):
    bot.add_cog(Basic(bot))
