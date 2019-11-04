from datetime import datetime, timedelta

import pytz
from discord.ext import commands
from pytz import UnknownTimeZoneError

from cogs.BaseCog import BaseCog
from utils import Utils, Lang


class Eden(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.cool_down = dict()

    def check_cool_down(self, user):
        if user.id in self.cool_down:
            min_time = 600
            start_time = self.cool_down[user.id]
            elapsed = datetime.now().timestamp() - start_time
            remaining = max(0, min_time - elapsed)
            if remaining <= 0:
                del self.cool_down[user.id]
                return 0
            else:
                return remaining
        return 0

    @commands.command(aliases=["edenreset", "er"])
    async def reset(self, ctx, tz=None):
        """Show information about reset time (and countdown) for Eye of Eden"""

        server_zone = pytz.timezone("America/Los_Angeles")
        try:
            if tz is None:
                tz = server_zone
            else:
                tz = pytz.timezone(tz)
        except UnknownTimeZoneError as e:
            await ctx.send(Lang.get_string('eden/tz_help', tz=tz))
            return

        cool_down = self.check_cool_down(ctx.author)
        if cool_down:
            v = Utils.to_pretty_time(cool_down)
            await ctx.send(f"Cool it, {ctx.author.mention}. Try again in {v}")
            return
        else:
            # start a new cool-down timer
            self.cool_down[ctx.author.id] = datetime.now().timestamp()

        # get a timestamp of today with the correct hour, eden reset is 7am UTC
        dt = datetime.now().astimezone(server_zone).replace(hour=0, minute=0, second=0, microsecond=0)
        # sunday is weekday 7
        days_to_go = (6 - dt.weekday()) or 7
        reset_time = dt + timedelta(days=days_to_go)

        time_left = reset_time - datetime.now().astimezone(server_zone)

        # convert to requested timezone
        reset_time_local = reset_time.astimezone(tz)

        pretty_countdown = Utils.to_pretty_time(time_left.total_seconds())
        pretty_date = reset_time_local.strftime("%A %B %d")
        pretty_time = reset_time_local.strftime("%H:%M %Z")

        await ctx.send(Lang.get_string("eden/reset", date=pretty_date, time=pretty_time, countdown=pretty_countdown))


def setup(bot):
    bot.add_cog(Eden(bot))
