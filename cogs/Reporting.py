from discord.ext import commands
from discord.ext.commands import command

from cogs.BaseCog import BaseCog
from utils import Configuration
from utils.Database import BugReport, Attachements


class Reporting(BaseCog):
    @command()
    async def csv(self, ctx: commands.Context, start=0, end=None, channel=None, branch=None):
        """Export bug reports starting from {start} to CSV file"""
        # TODO: start from ID or from date?
        # TODO: optionally export all channels/branches or individual
        query = (BugReport.select(BugReport))
        message = "report id, report time, reporter, platform, platform version, branch, app version, app build, " \
                  "report title, device info, steps, expected outcome, actual outcome, additional info\n"
        for report in query:
            reporter = self.bot.get_user(report.reporter)
            message += f"{report.id}, {report.reported_at}, @{reporter.name}#{reporter.discriminator}({report.reporter}), " \
                       f"'{report.platform}', '{report.platform_version}', '{report.branch}', '{report.app_version}', " \
                       f"'{report.app_build}', '{report.title}', '{report.deviceinfo}', '{report.steps}', " \
                       f"'{report.expected}', '{report.actual}', '{report.additional}'\n"
        sent = await ctx.send( message )

def setup(bot):
    bot.add_cog(Reporting(bot))
