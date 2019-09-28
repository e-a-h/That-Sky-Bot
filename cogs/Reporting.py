import os
import sys
from datetime import datetime

import typing
from discord import File
from discord.ext import commands
from discord.ext.commands import command

from cogs.BaseCog import BaseCog
from utils.Database import BugReport, Attachements, connection
from utils.Utils import save_to_disk


class Reporting(BaseCog):

    async def cog_check(self, ctx):
        return ctx.author.guild_permissions.ban_members  # or is_admin(ctx)

    @command(hidden=True)
    async def csv(
            self,
            ctx: commands.Context,
            start: typing.Optional[int] = 0,
            end: typing.Optional[int] = None,
            branch: typing.Optional[str] = "",
            platform: typing.Optional[str] = ""):
        """Export bug reports starting from {start} to CSV file
        csv                        exports complete history of reports
        csv 15 20                  exports reports with ids in the range 15-20
        csv -100                   exports the last 100 reports matching other criteria
        csv [both|beta|stable]        exports reports for given branch
        csv {both|beta|stable} [all|android|ios|etc]
                                   exports reports for given branch and platform"""
        # TODO: start from date?

        def get_branch(br):
            br = br.lower()
            if br == "beta":
                return ["Beta"]
            elif br == "stable":
                return ["Stable"]
            else:
                return ["Beta", "Stable"]

        def get_platform(pl):
            pl = pl.lower()
            if pl == "ios":
                return ["iOS"]
            elif pl == "android":
                return ["Android"]
            else:
                return ["Android", "iOS"]

        pl = get_platform(platform)
        br = get_branch(branch)

        sent = await ctx.send(
            f"Fetching bug reports...\n"
            f"start id: {start}\n"
            f"end id: {end}\n"
            f"branch: {br}\n"
            f"platform: {pl}\n"
        )

        conditions = (
            BugReport.branch.in_(br) &
            BugReport.platform.in_(pl) &
            (BugReport.id >= start) &
            (BugReport.id <= (sys.maxsize if end is None else end))
        )
        if start < 0:
            # count backward from end of data
            query = BugReport.select().where(conditions).order_by(BugReport.id.desc()).limit(abs(start))
        else:
            query = BugReport.select().where(conditions)  # .prefetch(Attachements)

        ids = []
        for row in query:
            ids.append(row.id)
        attachquery = Attachements.select().where(Attachements.report.in_(ids))

        for row in query:
            row.attachments = []
            for att in attachquery:
                if att.report_id == row.id:
                    row.attachments.append(att)

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
                  "attachments",
                  "additional"]
        data_list = ()
        for report in query:
            reporter = self.bot.get_user(report.reporter)
            attachments = []
            for attachment in report.attachments:
                attachments.append(attachment.url)

            attachments = "\n".join(attachments)

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
                           "attachments": attachments,
                           "additional": report.additional},)
        now = datetime.today().timestamp()

        out = ""
        for i in data_list:
            out += str(i) + "\n"

        sent = await ctx.send(f"Fetched {len(data_list)} reports...")
        save_to_disk(f"report_{now}", data_list, 'csv', fields)
        send_file = File(f"report_{now}.csv")
        sent = await ctx.send(file=send_file)
        os.remove(f"report_{now}.csv")


def setup(bot):
    bot.add_cog(Reporting(bot))
