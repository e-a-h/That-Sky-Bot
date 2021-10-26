import os
import re
import sys
from datetime import datetime

import typing
from discord import File
from discord.ext import commands
from discord.ext.commands import command

from cogs.BaseCog import BaseCog
from utils import Utils, Configuration
from utils.Database import BugReport, Attachments, connection, BugReportingPlatform
from utils.Utils import save_to_disk


class Reporting(BaseCog):

    fetch_limit = 1000

    async def cog_check(self, ctx):
        return Utils.can_mod_official(ctx)

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
        csv [both|beta|stable]     exports reports for given branch
        csv {both|beta|stable} [all|android|ios|etc]
                                   exports reports for given branch and platform"""
        # TODO: start from date?
        # TODO: migrate to async ORM like tortoise

        def get_branch(br):
            platforms = dict()
            branches = set()

            for row in BugReportingPlatform.select():
                branches.add(row.branch)
                if row.branch not in platforms:
                    platforms[row.branch] = set()
                platforms[row.branch].add(row.platform)

            br = br.lower().capitalize()
            if br in branches:
                return [br]
            return ["Beta", "Stable"]

        def get_platform(pl):
            platforms = dict()

            for row in BugReportingPlatform.select():
                platforms[row.platform.lower()] = row.platform

            pl = pl.lower()
            if pl in platforms:
                return [platforms[pl]]
            return ["Android", "iOS", "Switch"]

        # dashes at the start of text are interpreted as formulas by excel. replace with *
        def filter_hyphens(text):
            return re.sub(r'^\s*[-=+]\s*', '* ', text, flags=re.MULTILINE)

        pl = get_platform(platform)
        br = get_branch(branch)

        if start < -self.fetch_limit:
            await ctx.send(f"you requested more than {self.fetch_limit} records, "
                           f"so I'm only giving you {self.fetch_limit} because I'm a lazy bot")
            start = -self.fetch_limit

        try:
            # send feedback on command. Failure to send should end attempt.
            await ctx.send(
                f"Fetching bug reports...\n"
                f"start id: {start}\n"
                f"end id: {end}\n"
                f"branch: {br}\n"
                f"platform: {pl}\n"
            )
        except Exception as e:
            await Utils.handle_exception("failed to send reporting CSV startup message", self.bot, e)
            return

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
            query = BugReport.select().where(conditions).limit(self.fetch_limit)  # .prefetch(Attachments)

        ids = []
        for row in query:
            ids.append(row.id)
        attachquery = Attachments.select().where(Attachments.report.in_(ids))

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
            reporter_formatted = report.reporter
            reporter = self.bot.get_user(report.reporter)
            if reporter is not None:
                reporter_formatted = f"@{reporter.name}#{reporter.discriminator}({report.reporter})"
            attachments = []
            for attachment in report.attachments:
                attachments.append(attachment.url)

            attachments = "\n".join(attachments)

            data_list += ({"id": report.id,
                           "reported_at": report.reported_at,
                           "reporter": reporter_formatted,
                           "platform": report.platform,
                           "platform_version": report.platform_version,
                           "branch": report.branch,
                           "app_version": report.app_version,
                           "app_build": report.app_build,
                           "title": report.title,
                           "deviceinfo": report.deviceinfo,
                           "steps": filter_hyphens(report.steps),
                           "expected": filter_hyphens(report.expected),
                           "actual": filter_hyphens(report.actual),
                           "attachments": attachments,
                           "additional": filter_hyphens(report.additional)},)
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
