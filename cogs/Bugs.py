import asyncio
import copy
import re
import time
from concurrent.futures import CancelledError
from datetime import datetime

from discord import Forbidden, Embed, NotFound, HTTPException, PermissionOverwrite
from discord.ext import commands, tasks
from discord.ext.commands import Context, command

import prometheus_client as prom

from cogs.BaseCog import BaseCog
from utils import Questions, Emoji, Utils, Configuration, Lang, Logging
from utils.Database import BugReport, Attachments


class Bugs(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())
        self.bug_messages = set()
        self.in_progress = dict()
        self.sweeps = dict()
        self.blocking = set()
        self.maintenance_message = None
        self.maint_check_count = 0
        m = self.bot.metrics
        m.reports_in_progress.set_function(lambda: len(self.in_progress))

    def cog_unload(self):
        self.verify_empty_bug_queue.cancel()

    def can_mod(ctx):
        return ctx.author.guild_permissions.mute_members

    def can_admin(ctx):
        return ctx.author.guild_permissions.manage_channels

    async def sweep_trash(self, user, ctx):
        await asyncio.sleep(Configuration.get_var("bug_trash_sweep_minutes") * 60)
        if user.id in self.in_progress:
            if not self.in_progress[user.id].done() or not self.in_progress[user.id].cancelled():
                await user.send(Lang.get_locale_string("bugs/sweep_trash", ctx))
            await self.delete_progress(user.id)

    async def delete_progress(self, uid):
        if uid in self.in_progress:
            try:
                self.in_progress[uid].cancel()
            except Exception as e:
                # ignore task cancel failures
                pass
            del self.in_progress[uid]
        if uid in self.sweeps:
            self.sweeps[uid].cancel()

    async def shutdown(self):
        for name, cid in Configuration.get_var("channels").items():
            channel = self.bot.get_channel(cid)
            message = await channel.send(Lang.get_locale_string("bugs/shutdown_message"))
            Configuration.set_persistent_var(f"{name}_shutdown", message.id)

    async def startup_cleanup(self):
        for name, cid in Configuration.get_var("channels").items():
            channel = self.bot.get_channel(cid)
            shutdown_id = Configuration.get_persistent_var(f"{name}_shutdown")
            if shutdown_id is not None:
                try:
                    message = await channel.fetch_message(shutdown_id)
                    await message.delete()
                except (NotFound, HTTPException) as e:
                    pass
                Configuration.set_persistent_var(f"{name}_shutdown", None)
            try:
                await self.send_bug_info(name)
            except Exception as e:
                await Logging.bot_log(f'Bug message failed in {channel.mention}')

    async def send_bug_info(self, key):
        channel = self.bot.get_channel(Configuration.get_var("channels")[key])
        bug_info_id = Configuration.get_persistent_var(f"{key}_message")

        last_message = await channel.history(limit=1).flatten()
        last_message = last_message[0]
        ctx = await self.bot.get_context(last_message)

        if bug_info_id is not None:
            try:
                message = await channel.fetch_message(bug_info_id)
            except (NotFound, HTTPException):
                pass
            else:
                await message.delete()
                if message.id in self.bug_messages:
                    self.bug_messages.remove(message.id)

        bugemoji = Emoji.get_emoji('BUG')
        message = await channel.send(Lang.get_locale_string("bugs/bug_info", ctx, bug_emoji=bugemoji))
        await message.add_reaction(bugemoji)
        self.bug_messages.add(message.id)
        Configuration.set_persistent_var(f"{key}_message", message.id)

    @tasks.loop(seconds=30.0)
    async def verify_empty_bug_queue(self, ctx):
        if len(self.in_progress) > 0:

            if self.maint_check_count == 10:
                await ctx.send(Lang.get_locale_string('bugs/maint_check_fail', ctx, author=ctx.author.mention))
                self.verify_empty_bug_queue.cancel()
                return

            msg = f"There are {len(self.in_progress)} report(s) still in progress."
            if self.maintenance_message is None:
                self.maintenance_message = await ctx.send(msg)
            else:
                self.maint_check_count = self.maint_check_count + 1
                await self.maintenance_message.edit(content=msg + (" ." * self.maint_check_count))
            return
        elif self.maint_check_count > 0:
            await self.maintenance_message.delete()
            await ctx.send(Lang.get_locale_string('bugs/bugs_all_done', ctx, author=ctx.author.mention))
        else:
            await ctx.send(Lang.get_locale_string('bugs/none_in_progress', ctx))

        self.maintenance_message = None
        self.verify_empty_bug_queue.cancel()

    @commands.command(aliases=["bugmaint", "maintenance", "maintenance_mode", "maint"])
    @commands.guild_only()
    @commands.check(can_mod)
    async def bug_maintenance(self, ctx, active: bool):
        """
        Bot maintenance mode.

        Closes bug reporting channels and opens bug maintenance channel.
        Watches active bug reports for 10 minutes or so to give people a chance to finish reports in progress.
        """
        try:
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
        except Exception as e:
            await ctx.send(Lang.get_locale_string('bugs/report_channel_permissions_fail', ctx))
            await Utils.handle_exception("failed to set bug report channel permissions", self.bot, e)
        else:
            if active:
                self.maint_check_count = 0
                self.verify_empty_bug_queue.start(ctx)
                await ctx.send(Lang.get_locale_string('bugs/maint_on', ctx))
            else:
                await ctx.send(Lang.get_locale_string('bugs/maint_off', ctx))

    @commands.group(name='bug', invoke_without_command=True)
    async def bug(self, ctx: Context):
        """Report a bug!"""
        # remove command to not flood chat (unless we are in a DM already)
        if ctx.guild is not None:
            await ctx.message.delete()
        await self.report_bug(ctx.author, ctx.channel)

    @bug.command(aliases=["resetactive", "reset_in_progress", "resetinprogress", "reset", "clean"])
    @commands.guild_only()
    @commands.check(can_admin)
    async def reset_active(self, ctx):
        """Reset active bug reports. Bot will attempt to DM users whose reports are cancelled."""
        to_kill = len(self.in_progress)
        active_keys = [key for key in self.in_progress.keys()]
        for uid in active_keys:
            try:
                await self.delete_progress(uid)
                user = self.bot.get_user(uid)
                await user.send(Lang.get_locale_string('bugs/user_reset',
                                                       Configuration.get_var('broadcast_locale', 'en_US')))
            except Exception as e:
                await ctx.send(f"can't reset bug report for <@{uid}>")
        self.in_progress = dict()
        await ctx.send(Lang.get_locale_string('bugs/dead_bugs_cleaned',
                                              ctx,
                                              active_keys=len(active_keys),
                                              in_progress=len(self.in_progress)))

    async def report_bug(self, user, trigger_channel):
        # fully ignore muted users
        m = self.bot.metrics
        last_message = await trigger_channel.history(limit=1).flatten()
        last_message = last_message[0]
        ctx = await self.bot.get_context(last_message)
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
                await ctx.send(Lang.get_locale_string("bugs/stop_spamming", ctx, user=user.mention), delete_after=10)
                return

            should_reset = False

            async def start_over():
                nonlocal should_reset
                should_reset = True

            # block more clicks to the initial trigger
            self.blocking.add(user.id)

            # ask if user wants to start over
            await Questions.ask(self.bot, trigger_channel, user,
                                Lang.get_locale_string("bugs/start_over", ctx, user=user.mention),
                                [
                                    Questions.Option("YES", Lang.get_locale_string("bugs/start_over_yes", ctx),
                                                     handler=start_over),
                                    Questions.Option("NO", Lang.get_locale_string("bugs/start_over_no", ctx))
                                ], delete_after=True, show_embed=True, locale=ctx)

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
        sweep = self.bot.loop.create_task(self.sweep_trash(user, ctx))
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
            last_message = await trigger_channel.history(limit=1).flatten()
            last_message = last_message[0]
            ctx = await self.bot.get_context(last_message)

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
                await user.send(Lang.get_locale_string("bugs/abort_report", ctx))
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
                    return Lang.get_locale_string("bugs/latest_not_allowed", ctx)
                # TODO: double check if we actually want to enforce this
                if len(Utils.NUMBER_MATCHER.findall(v)) == 0:
                    return Lang.get_locale_string("bugs/no_numbers", ctx)
                if len(v) > 20:
                    return Lang.get_locale_string("bugs/love_letter", ctx)
                return True

            def max_length(length):
                def real_check(text):
                    if len(text) > length:
                        return Lang.get_locale_string("bugs/text_too_long", ctx, max=length)
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
                    content=Lang.get_locale_string("bugs/report_header", ctx, id=br.id, user=user.mention),
                    embed=report)
                if len(attachment_links) != 0:
                    key = "attachment_info" if len(attachment_links) == 1 else "attachment_info_plural"
                    attachment = await self.bot.get_channel(c).send(
                        Lang.get_locale_string(f"bugs/{key}", ctx, id=br.id, links="\n".join(attachment_links)))
                    br.attachment_message_id = attachment.id
                br.message_id = message.id
                br.save()
                await channel.send(Lang.get_locale_string("bugs/report_confirmation", ctx, channel_id=c))
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
            await Questions.ask(self.bot, channel, user, Lang.get_locale_string("bugs/question_ready", ctx),
                                [
                                    Questions.Option("YES", "Press this reaction to answer YES and begin a report"),
                                    Questions.Option("NO", "Press this reaction to answer NO", handler=abort),
                                ], show_embed=True, locale=ctx)
            update_metrics()

            if asking:
                # question 1: android or ios?
                await Questions.ask(self.bot, channel, user, Lang.get_locale_string("bugs/question_platform", ctx),
                                    [
                                        Questions.Option("ANDROID", "Android", lambda: set_platform("Android")),
                                        Questions.Option("IOS", "iOS", lambda: set_platform("iOS"))
                                    ], show_embed=True, locale=ctx)
                update_metrics()

                # question 2: android/ios version
                platform_version = await Questions.ask_text(self.bot, channel, user,
                                                            Lang.get_locale_string("bugs/question_platform_version",
                                                                                   ctx,
                                                                                   platform=platform),
                                                            validator=verify_version, locale=ctx)
                update_metrics()

                # question 3: hardware info
                deviceinfo = await Questions.ask_text(self.bot, channel, user,
                                                      Lang.get_locale_string("bugs/question_device_info",
                                                                             ctx, platform=platform, max=200),
                                                      validator=max_length(200), locale=ctx)
                update_metrics()

                # question 4: stable or beta?
                await Questions.ask(self.bot, channel, user, Lang.get_locale_string("bugs/question_app_branch", ctx),
                                    [
                                        Questions.Option("STABLE", "Live", lambda: set_branch("Stable")),
                                        Questions.Option("BETA", "Beta", lambda: set_branch("Beta"))
                                    ], show_embed=True, locale=ctx)
                update_metrics()

                # question 5: sky app version
                app_version = await Questions.ask_text(
                    self.bot,
                    channel,
                    user,
                    Lang.get_locale_string(
                        "bugs/question_app_version", ctx,
                        version_help=Lang.get_locale_string("bugs/version_" + platform.lower())),
                    validator=verify_version, locale=ctx)
                update_metrics()

                # question 6: sky app build number
                app_build = await Questions.ask_text(
                    self.bot, channel, user, Lang.get_locale_string("bugs/question_app_build", ctx),
                    validator=verify_version, locale=ctx)
                update_metrics()

                # question 7: Title
                title = await Questions.ask_text(
                    self.bot, channel, user, Lang.get_locale_string("bugs/question_title", ctx, max=300),
                    validator=max_length(300), locale=ctx)
                update_metrics()

                # question 8: "actual" - defect behavior
                actual = await Questions.ask_text(
                    self.bot, channel, user, Lang.get_locale_string("bugs/question_actual", ctx, max=800),
                    validator=max_length(800), locale=ctx)
                update_metrics()

                # question 9: steps to reproduce
                steps = await Questions.ask_text(
                    self.bot, channel, user, Lang.get_locale_string("bugs/question_steps", ctx, max=800),
                    validator=max_length(800), locale=ctx)
                update_metrics()

                # question 10: expected behavior
                expected = await Questions.ask_text(
                    self.bot, channel, user,
                    Lang.get_locale_string("bugs/question_expected", ctx, max=800),
                    validator=max_length(800), locale=ctx)
                update_metrics()

                # question 11: attachments y/n
                await Questions.ask(
                    self.bot, channel, user, Lang.get_locale_string("bugs/question_attachments", ctx),
                    [
                        Questions.Option("YES",
                                         Lang.get_locale_string("bugs/attachments_yes", ctx),
                                         handler=add_attachments),
                        Questions.Option("NO", Lang.get_locale_string("bugs/skip_step", ctx))
                    ], show_embed=True, locale=ctx)
                update_metrics()

                if attachments:
                    # question 12: attachments
                    attachment_links = await Questions.ask_attachements(self.bot, channel, user, locale=ctx)
                # update metrics outside condition to keep count up-to-date and reflect skipped question as zero time
                update_metrics()

                # question 13: additional info y/n
                await Questions.ask(
                    self.bot, channel, user, Lang.get_locale_string("bugs/question_additional", ctx),
                    [
                        Questions.Option("YES",
                                         Lang.get_locale_string("bugs/additional_info_yes", ctx),
                                         handler=add_additional),
                        Questions.Option("NO", Lang.get_locale_string("bugs/skip_step", ctx))
                    ], show_embed=True, locale=ctx)
                update_metrics()

                if additional:
                    # question 14: additional info
                    additional_text = await Questions.ask_text(
                        self.bot, channel, user,
                        Lang.get_locale_string("bugs/question_additional_info", ctx),
                        validator=max_length(500), locale=ctx)
                # update metrics outside condition to keep count up-to-date and reflect skipped question as zero time
                update_metrics()

                # assemble the report and show to user for review
                report = Embed(timestamp=datetime.utcfromtimestamp(time.time()))
                report.set_author(name=f"{user} ({user.id})", icon_url=user.avatar_url_as(size=32))
                report.add_field(
                    name=Lang.get_locale_string("bugs/platform", ctx), value=f"{platform} {platform_version}")
                report.add_field(
                    name=Lang.get_locale_string("bugs/app_version", ctx), value=app_version)
                report.add_field(
                    name=Lang.get_locale_string("bugs/app_build", ctx), value=app_build)
                report.add_field(
                    name=Lang.get_locale_string("bugs/device_info", ctx), value=deviceinfo, inline=False)
                report.add_field(
                    name=Lang.get_locale_string("bugs/title", ctx), value=title, inline=False)
                report.add_field(
                    name=Lang.get_locale_string("bugs/description", ctx), value=actual, inline=False)
                report.add_field(
                    name=Lang.get_locale_string("bugs/steps_to_reproduce", ctx), value=steps, inline=False)
                report.add_field(
                    name=Lang.get_locale_string("bugs/expected", ctx), value=expected)
                if additional:
                    report.add_field(
                        name=Lang.get_locale_string("bugs/additional_info", ctx), value=additional_text, inline=False)

                await channel.send(
                    content=Lang.get_locale_string("bugs/report_header", ctx, id="##", user=user.mention), embed=report)
                if attachment_links:
                    attachment_message = ''
                    for a in attachment_links:
                        attachment_message += f"{a}\n"
                    await channel.send(attachment_message)

                review_time = 300
                await asyncio.sleep(1)

                # Question 15 - final review
                await Questions.ask(
                    self.bot, channel, user,
                    Lang.get_locale_string("bugs/question_ok", ctx, timeout=Questions.timeout_format(review_time)),
                    [
                        Questions.Option("YES", Lang.get_locale_string("bugs/send_report", ctx), send_report),
                        Questions.Option("NO", Lang.get_locale_string("bugs/mistake", ctx), restart)
                    ], show_embed=True, timeout=review_time, locale=ctx)
                update_metrics()
                report_duration = time.time() - report_start_time
                m.reports_duration.set(report_duration)
            else:
                return

        except Forbidden as ex:
            m.bot_cannot_dm_member.inc()
            await trigger_channel.send(
                Lang.get_locale_string("bugs/dm_unable", ctx, user=user.mention),
                delete_after=30)
        except asyncio.TimeoutError as ex:
            m.report_incomplete_count.inc()
            await channel.send(Lang.get_locale_string("bugs/report_timeout", ctx))
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
            try:
                message = await channel.fetch_message(event.message_id)
                await message.remove_reaction(event.emoji, user)
            except (NotFound, HTTPException) as e:
                await Utils.handle_exception(f"Failed to get message {channel.id}/{event.message_id}", self, e)
                # TODO: Does anyone need to know about this?
                #  Consider letter user know why report didn't start?
                return
            await self.report_bug(user, channel)


def setup(bot):
    bot.add_cog(Bugs(bot))
