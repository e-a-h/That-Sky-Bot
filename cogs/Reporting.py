import os
from datetime import datetime

from discord import File
from discord.ext import commands
from discord.ext.commands import command

from cogs.BaseCog import BaseCog
from utils.Database import BugReport, Attachements
from utils.Utils import save_to_disk, is_admin


class Reporting(BaseCog):
    @command()
    async def csv(self, ctx: commands.Context, start=0, end=None, channel=None, branch=None):
        """Export bug reports starting from {start} to CSV file"""
        # TODO: start from ID or from date?
        # TODO: optionally export all channels/branches or individual
        # TODO: join attachments table to this output

        if not is_admin(ctx.author):
            return

        query = (BugReport.select(BugReport))

        fields = ["id",
                  "reported_at",
                  "reporter",
                  "platform",
                  "platform_version",
                  "branch",
                  "app_version",
                  "app_build",
                  "title",
                  "deviceinfo",
                  "steps",
                  "expected",
                  "actual",
                  "additional"]
        data_list = ()
        for report in query:
            reporter = self.bot.get_user(report.reporter)
            data_list += ({"id": report.id,
                           "reported_at": report.reported_at,
                           "reporter": f"@{reporter.name}#{reporter.discriminator}({report.reporter})",
                           "platform": report.platform,
                           "platform_version": report.platform_version,
                           "branch": report.branch,
                           "app_version": report.app_version,
                           "app_build": report.app_build,
                           "title": report.title,
                           "deviceinfo": report.deviceinfo,
                           "steps": report.steps,
                           "expected": report.expected,
                           "actual": report.actual,
                           "additional": report.additional},)
        now = datetime.today().timestamp()
        save_to_disk(f"report_{now}", data_list, 'csv', fields)
        send_file = File(f"report_{now}.csv")
        sent = await ctx.send(file=send_file)
        os.remove(f"report_{now}.csv")


def setup(bot):
    bot.add_cog(Reporting(bot))
