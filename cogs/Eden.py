import datetime

import pytz
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Utils, Lang
from utils.Converters import Timezone


class Eden(BaseCog):

    @commands.command(aliases=["edenreset", "er"])
    async def reset(self, ctx, tz:Timezone=pytz.timezone("America/Los_Angeles")):
        """Show information about reset time (and countdown) for Eye of Eden"""
        server_zone = pytz.timezone("America/Los_Angeles")
        # get a timestamp of today with the correct hour, eden reset is 7am UTC
        dt = datetime.datetime.now().astimezone(server_zone).replace(hour=0, minute=0, second=0, microsecond=0)
        # sunday is weekday 7
        days_to_go = (6 - dt.weekday()) if dt.weekday() < 6 else 7
        reset_time = dt + datetime.timedelta(days=days_to_go)

        time_left = reset_time - datetime.datetime.now().astimezone(server_zone)

        # convert to requested timezone
        reset_time_local = reset_time.astimezone(tz)

        pretty_countdown = Utils.to_pretty_time(time_left.total_seconds())
        pretty_date = reset_time_local.strftime("%A %B %d")
        pretty_time = reset_time_local.strftime("%H:%M %Z")

        await ctx.send(Lang.get_string("eden_reset", date=pretty_date, time=pretty_time, countdown=pretty_countdown))


def setup(bot):
    bot.add_cog(Eden(bot))
