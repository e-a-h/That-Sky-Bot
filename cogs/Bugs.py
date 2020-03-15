import asyncio
import re
import time
from concurrent.futures import CancelledError
from datetime import datetime

from discord import Forbidden, Embed, NotFound, PermissionOverwrite
from discord.ext import commands
from discord.ext.commands import Context, command

import prometheus_client as prom

from cogs.BaseCog import BaseCog
from utils import Questions, Emoji, Utils, Configuration, Lang
from utils.Database import BugReport, Attachments


class Bugs(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())
        self.bug_messages = set()
        self.in_progress = dict()
        self.sweeps = dict()
        self.blocking = set()
        m = self.bot.metrics
        m.reports_in_progress.set_function(lambda: len(self.in_progress))

    async def sweep_trash(self, user):
        await asyncio.sleep(Configuration.get_var("bug_trash_sweep_minutes")*60)
        if user.id in self.in_progress:
            if not self.in_progress[user.id].done() or not self.in_progress[user.id].cancelled():
                await user.send(Lang.get_string("bugs/sweep_trash"))

            await self.delete_progress(user.id)

    async def delete_progress(self, uid):
        if uid in self.in_progress:
            self.in_progress[uid].cancel()
            del self.in_progress[uid]
        if uid in self.sweeps:
            self.sweeps[uid].cancel()

    async def shutdown(self):
        for name, cid in Configuration.get_var("channels").items():
            channel = self.bot.get_channel(cid)
            message = await channel.send(Lang.get_string("bugs/shutdown_message"))
            Configuration.set_persistent_var(f"{name}_shutdown", message.id)

    async def startup_cleanup(self):
        for name, cid in Configuration.get_var("channels").items():
            channel = self.bot.get_channel(cid)
            shutdown_id = Configuration.get_persistent_var(f"{name}_shutdown")
            if shutdown_id is not None:
                message = await channel.fetch_message(shutdown_id)
                if message is not None:
                    await message.delete()
                Configuration.set_persistent_var(f"{name}_shutdown", None)
            await self.send_bug_info(name)

    async def send_bug_info(self, key):
        channel = self.bot.get_channel(Configuration.get_var("channels")[key])
        bug_info_id = Configuration.get_persistent_var(f"{key}_message")
        if bug_info_id is not None:
            try:
                message = await channel.fetch_message(bug_info_id)
            except NotFound:
                pass
            else:
                await message.delete()
                if message.id in self.bug_messages:
                    self.bug_messages.remove(message.id)

        bugemoji = Emoji.get_emoji('BUG')
        message = await channel.send(Lang.get_string("bugs/bug_info", bug_emoji=bugemoji))
        await message.add_reaction(bugemoji)
        self.bug_messages.add(message.id)
        Configuration.set_persistent_var(f"{key}_message", message.id)

    @commands.command(aliases=["bugmaint"])
    @commands.guild_only()
    @commands.is_owner()
    async def bug_maintenance(self, ctx, active: bool):
        if active:
            if len(self.in_progress) > 0:
                await ctx.send(f"There are {len(self.in_progress)} report(s) in progress. Not activating maintenance mode.")
                return
            await ctx.send("setting bug maintenance mode **on**: Reporting channels **closed**.")
        else:
            await ctx.send("setting bug maintenance mode **off**: Reporting channels **open**.")
        pass

        # show/hide maintenance channel
        maint_message_channel = self.bot.get_channel(Configuration.get_var("bug_maintenance_channel"))

        member_role = ctx.guild.get_role(Configuration.get_var("member_role"))
        beta_role = ctx.guild.get_role(Configuration.get_var("beta_role"))

        member_overwrite = maint_message_channel.overwrites[member_role]
        member_overwrite.read_messages = active
        await maint_message_channel.set_permissions(member_role, overwrite=member_overwrite)

        beta_overwrite = maint_message_channel.overwrites[beta_role]
        beta_overwrite.read_messages = active
        await maint_message_channel.set_permissions(beta_role, overwrite=beta_overwrite)

        for name, cid in Configuration.get_var("channels").items():
            # show/hide reporting channels
            channel = self.bot.get_channel(cid)

            member_overwrite = channel.overwrites[member_role]
            member_overwrite.read_messages = None if active else True
            await channel.set_permissions(member_role, overwrite=member_overwrite)

            if re.search(r'beta', name):
                beta_overwrite = channel.overwrites[beta_role]
                beta_overwrite.read_messages = None if active else True
                await channel.set_permissions(beta_role, overwrite=beta_overwrite)

    @commands.group(name='bug', invoke_without_command=True)
    async def bug(self, ctx: Context):
        # remove command to not flood chat (unless we are in a DM already)
        if ctx.guild is not None:
            await ctx.message.delete()
        await self.report_bug(ctx.author, ctx.channel)

    @commands.guild_only()
    @bug.command(aliases=["resetactive", "reset_in_progress", "resetinprogress", "reset", "clean"])
    async def reset_active(self, ctx):
        is_owner = await ctx.bot.is_owner(ctx.author)
        if is_owner:
            to_kill = len(self.in_progress)
            active_keys = self.in_progress.keys()
            for uid in active_keys:
                await self.delete_progress(uid)
            self.in_progress = dict()
            await ctx.send(f"Ok. Number of dead bugs cleaned up: {active_keys}. Number still alive: {len(self.in_progress)}")

    async def report_bug(self, user, trigger_channel):
        # fully ignore muted users
        m = self.bot.metrics
        await asyncio.sleep(1)
        guild = self.bot.get_guild(Configuration.get_var("guild_id"))
        member = guild.get_member(user.id)
        mute_role = guild.get_role(Configuration.get_var("muted_role"))
        if member is None:
            # user isn't even on the server, how did we get here?
            return
        if mute_role in member.roles:
            # muted, hard ignore
            return

        if user.id in self.in_progress:
            # already tracking progress for this user
            if user.id in self.blocking:
                # user blocked from starting a new report. waiting for DM response
                await trigger_channel.send(Lang.get_string("bugs/stop_spamming", user=user.mention), delete_after=10)
                return

            should_reset = False

            async def start_over():
                nonlocal should_reset
                should_reset = True

            # block more clicks to the initial trigger
            self.blocking.add(user.id)

            # ask if user wants to start over
            await Questions.ask(self.bot, trigger_channel, user, Lang.get_string("bugs/start_over", user=user.mention),
                                [
                                    Questions.Option("YES", Lang.get_string("bugs/start_over_yes"), handler=start_over),
                                    Questions.Option("NO", Lang.get_string("bugs/start_over_no"))
                                ], delete_after=True, show_embed=True)

            # not starting over. remove blocking
            if user.id in self.blocking:
                self.blocking.remove(user.id)

            # cancel running task, delete progress, and fall through to start a new report
            await self.delete_progress(user.id)
            if not should_reset:
                # in-progress report should not be reset. bail out
                return

        # Start a bug report
        task = self.bot.loop.create_task(self.actual_bug_reporter(user, trigger_channel))
        sweep = self.bot.loop.create_task(self.sweep_trash(user))
        self.in_progress[user.id] = task
        self.sweeps[user.id] = sweep
        try:
            await task
        except CancelledError as ex:
            pass

    async def actual_bug_reporter(self, user, trigger_channel):
        # wrap everything so users can't get stuck in limbo
        m = self.bot.metrics
        active_question = None
        restarting = False
        try:
            channel = await user.create_dm()

            # vars to store everything
            asking = True
            platform = ""
            branch = ""
            app_build = None
            additional = False
            additional_text = ""
            attachments = False
            attachment_links = []
            report = None

            # define all the parts we need as inner functions for easier sinfulness

            async def abort():
                nonlocal asking
                await user.send(Lang.get_string("bugs/abort_report"))
                asking = False
                m.reports_abort_count.inc()
                m.reports_exit_question.observe(active_question)
                await self.delete_progress(user.id)

            def set_platform(p):
                nonlocal platform
                platform = p

            def set_branch(b):
                nonlocal branch
                branch = b

            def add_additional():
                nonlocal additional
                additional = True

            def add_attachments():
                nonlocal attachments
                attachments = True

            def verify_version(v):
                if "latest" in v:
                    return Lang.get_string("bugs/latest_not_allowed")
                # TODO: double check if we actually want to enforce this
                if len(Utils.NUMBER_MATCHER.findall(v)) == 0:
                    return Lang.get_string("bugs/no_numbers")
                if len(v) > 20:
                    return Lang.get_string("bugs/love_letter")
                return True

            def max_length(length):
                def real_check(text):
                    if len(text) > length:
                        return Lang.get_string("bugs/text_too_long", max=length)
                    return True

                return real_check

            async def send_report():
                # save report in the database
                br = BugReport.create(reporter=user.id, platform=platform, deviceinfo=deviceinfo,
                                      platform_version=platform_version, branch=branch, app_version=app_version,
                                      app_build=app_build, title=title, steps=steps, expected=expected, actual=actual,
                                      additional=additional_text)
                for url in attachment_links:
                    Attachments.create(report=br, url=url)

                # send report
                channel_name = f"{platform}_{branch}".lower()
                c = Configuration.get_var("channels")[channel_name]
                message = await self.bot.get_channel(c).send(
                    content=Lang.get_string("bugs/report_header", id=br.id, user=user.mention), embed=report)
                if len(attachment_links) != 0:
                    key = "attachment_info" if len(attachment_links) == 1 else "attachment_info_plural"
                    attachment = await self.bot.get_channel(c).send(
                        Lang.get_string(f"bugs/{key}", id=br.id, links="\n".join(attachment_links)))
                    br.attachment_message_id = attachment.id
                br.message_id = message.id
                br.save()
                await channel.send(Lang.get_string("bugs/report_confirmation", channel_id=c))
                await self.send_bug_info(channel_name)

            async def restart():
                nonlocal restarting
                restarting = True
                m.reports_restarted.inc()
                await self.delete_progress(user.id)
                self.bot.loop.create_task(self.report_bug(user, trigger_channel))

            # start global report timer and question timer
            report_start_time = question_start_time = time.time()
            m.reports_started.inc()

            def update_metrics():
                nonlocal active_question
                nonlocal question_start_time

                now = time.time()
                question_duration = now - question_start_time
                question_start_time = now

                # Record the time taken to answer the previous question
                gauge = getattr(m, f"reports_question_{active_question}_duration")
                gauge.set(question_duration)

                active_question = active_question + 1

            active_question = 0
            await Questions.ask(self.bot, channel, user, Lang.get_string("bugs/question_ready"),
                                [
                                    Questions.Option("YES", "Press this reaction to answer YES and begin a report"),
                                    Questions.Option("NO", "Press this reaction to answer NO", handler=abort),
                                ], show_embed=True)
            update_metrics()

            if asking:
                # question 1: android or ios?
                await Questions.ask(self.bot, channel, user, Lang.get_string("bugs/question_platform"),
                                    [
                                        Questions.Option("ANDROID", "Android", lambda: set_platform("Android")),
                                        Questions.Option("IOS", "iOS", lambda: set_platform("iOS"))
                                    ], show_embed=True)
                update_metrics()

                # question 2: android/ios version
                platform_version = await Questions.ask_text(self.bot, channel, user,
                                                            Lang.get_string("bugs/question_platform_version",
                                                                            platform=platform),
                                                            validator=verify_version)
                update_metrics()

                # question 3: hardware info
                deviceinfo = await Questions.ask_text(self.bot, channel, user,
                                                      Lang.get_string("bugs/question_device_info",
                                                                      platform=platform, max=200),
                                                      validator=max_length(200))
                update_metrics()

                # question 4: stable or beta?
                await Questions.ask(self.bot, channel, user, Lang.get_string("bugs/question_app_branch"),
                                    [
                                        Questions.Option("STABLE", "Live", lambda: set_branch("Stable")),
                                        Questions.Option("BETA", "Beta", lambda: set_branch("Beta"))
                                    ], show_embed=True)
                update_metrics()

                # question 5: sky app version
                app_version = await Questions.ask_text(self.bot,
                                                       channel,
                                                       user,
                                                       Lang.get_string(
                                                           "bugs/question_app_version",
                                                           version_help=Lang.get_string("bugs/version_" + platform.lower())),
                                                       validator=verify_version)
                update_metrics()

                # question 6: sky app build number
                app_build = await Questions.ask_text(self.bot, channel, user, Lang.get_string("bugs/question_app_build"),
                                                     validator=verify_version)
                update_metrics()

                # question 7: Title
                title = await Questions.ask_text(self.bot, channel, user, Lang.get_string("bugs/question_title", max=300),
                                                 validator=max_length(300))
                update_metrics()

                # question 8: "actual" - defect behavior
                actual = await Questions.ask_text(self.bot, channel, user, Lang.get_string("bugs/question_actual", max=800),
                                                  validator=max_length(800))
                update_metrics()

                # question 9: steps to reproduce
                steps = await Questions.ask_text(self.bot, channel, user, Lang.get_string("bugs/question_steps", max=800),
                                                 validator=max_length(800))
                update_metrics()

                # question 10: expected behavior
                expected = await Questions.ask_text(self.bot, channel, user,
                                                    Lang.get_string("bugs/question_expected", max=800),
                                                    validator=max_length(800))
                update_metrics()

                # question 11: attachments y/n
                await Questions.ask(self.bot, channel, user, Lang.get_string("bugs/question_attachments"),
                                    [
                                        Questions.Option("YES", Lang.get_string("bugs/attachments_yes"), handler=add_attachments),
                                        Questions.Option("NO", Lang.get_string("bugs/skip_step"))
                                    ], show_embed=True)
                update_metrics()

                if attachments:
                    # question 12: attachments
                    attachment_links = await Questions.ask_attachements(self.bot, channel, user)
                # update metrics outside condition to keep count up-to-date and reflect skipped question as zero time
                update_metrics()

                # question 13: additional info y/n
                await Questions.ask(self.bot, channel, user, Lang.get_string("bugs/question_additional"),
                                    [
                                        Questions.Option("YES", Lang.get_string("bugs/additional_info_yes"), handler=add_additional),
                                        Questions.Option("NO", Lang.get_string("bugs/skip_step"))
                                    ], show_embed=True)
                update_metrics()

                if additional:
                    # question 14: additional info
                    additional_text = await Questions.ask_text(self.bot, channel, user,
                                                               Lang.get_string("bugs/question_additional_info"),
                                                               validator=max_length(500))
                # update metrics outside condition to keep count up-to-date and reflect skipped question as zero time
                update_metrics()

                # assemble the report and show to user for review
                report = Embed(timestamp=datetime.utcfromtimestamp(time.time()))
                report.set_author(name=f"{user} ({user.id})", icon_url=user.avatar_url_as(size=32))
                report.add_field(name=Lang.get_string("bugs/platform"), value=f"{platform} {platform_version}")
                report.add_field(name=Lang.get_string("bugs/app_version"), value=app_version)
                report.add_field(name=Lang.get_string("bugs/app_build"), value=app_build)
                report.add_field(name=Lang.get_string("bugs/device_info"), value=deviceinfo, inline=False)
                report.add_field(name=Lang.get_string("bugs/title"), value=title, inline=False)
                report.add_field(name=Lang.get_string("bugs/description"), value=actual, inline=False)
                report.add_field(name=Lang.get_string("bugs/steps_to_reproduce"), value=steps, inline=False)
                report.add_field(name=Lang.get_string("bugs/expected"), value=expected)
                if additional:
                    report.add_field(name=Lang.get_string("bugs/additional_info"), value=additional_text, inline=False)

                await channel.send(content=Lang.get_string("bugs/report_header", id="##", user=user.mention), embed=report)
                if attachment_links:
                    attachment_message = ''
                    for a in attachment_links:
                        attachment_message += f"{a}\n"
                    await channel.send(attachment_message)

                review_time = 300
                await asyncio.sleep(1)

                # Question 15 - final review
                await Questions.ask(self.bot, channel, user,
                                    Lang.get_string("bugs/question_ok", timeout=Questions.timeout_format(review_time)),
                                    [
                                        Questions.Option("YES", Lang.get_string("bugs/send_report"), send_report),
                                        Questions.Option("NO", Lang.get_string("bugs/mistake"), restart)
                                    ], show_embed=True, timeout=review_time)
                update_metrics()
                report_duration = time.time() - report_start_time
                m.reports_duration.set(report_duration)
            else:
                return

        except Forbidden as ex:
            m.bot_cannot_dm_member.inc()
            await trigger_channel.send(
                Lang.get_string("bugs/dm_unable", user=user.mention),
                delete_after=30)
        except asyncio.TimeoutError as ex:
            m.report_incomplete_count.inc()
            await channel.send(Lang.get_string("bugs/report_timeout"))
            if active_question is not None:
                m.reports_exit_question.observe(active_question)
            self.bot.loop.create_task(self.delete_progress(user.id))
        except CancelledError as ex:
            m.report_incomplete_count.inc()
            if active_question is not None:
                m.reports_exit_question.observe(active_question)
            if not restarting:
                raise ex
        except Exception as ex:
            self.bot.loop.create_task(self.delete_progress(user.id))
            await Utils.handle_exception("bug reporting", self.bot, ex)
            raise ex
        else:
            self.bot.loop.create_task(self.delete_progress(user.id))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        if event.message_id in self.bug_messages and event.user_id != self.bot.user.id:
            user = self.bot.get_user(event.user_id)
            channel = self.bot.get_channel(event.channel_id)
            message = await channel.fetch_message(event.message_id)
            await message.remove_reaction(event.emoji, user)
            await self.report_bug(user, channel)


def setup(bot):
    bot.add_cog(Bugs(bot))
