import time

from discord.ext.commands import command, Context
from datetime import datetime

from cogs.BaseCog import BaseCog
from utils import Utils


class Basic(BaseCog):

    async def cog_check(self, ctx):
        return await Utils.permission_official_mute(ctx)

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
        edited_message = await message.edit(
            content=f":hourglass: REST API ping is {rest} ms | Websocket ping is {latency} ms :hourglass:")

    @command()
    async def now(self, ctx, *args):
        if ctx.author.bot or not await Utils.can_mod_official(ctx):
            return

        now = int(datetime.now().timestamp())
        formats = {
            'd': f"<t:{now}:d>",
            'D': f"<t:{now}:D>",
            't': f"<t:{now}:t>",
            'T': f"<t:{now}:T>",
            'f': f"<t:{now}:f>",
            'F': f"<t:{now}:F>",
            'R': f"<t:{now}:R>",
            's': f"{now}"
        }
        dates_formatted = []

        format_requested = False
        for arg in set(args):
            if arg in formats:
                dates_formatted.append(f"`{formats[arg]}` {formats[arg]}")
                format_requested = True

        if not format_requested:
            for arg in formats:
                dates_formatted.append(f"`{formats[arg]}` {formats[arg]}")

        if dates_formatted:
            output = "\n".join(dates_formatted)
        else:
            output = "No valid format requested"

        await ctx.send(output)


async def setup(bot):
    await bot.add_cog(Basic(bot))
