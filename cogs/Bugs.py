import asyncio
import re
import time
from concurrent.futures import CancelledError
from datetime import datetime

from discord import Forbidden, Embed, NotFound, HTTPException, TextChannel
from discord.ext import commands, tasks
from discord.ext.commands import Context, clean_content
from peewee import DoesNotExist, IntegrityError

from cogs.BaseCog import BaseCog
from sky import Skybot
from utils import Questions, Emoji, Utils, Configuration, Lang, Logging
from utils.Database import BugReport, Attachments, BugReportingPlatform, BugReportingChannel, Guild


class Bugs(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.bug_messages = set()
        self.in_progress = dict()
        self.sweeps = dict()
        self.blocking = set()
        self.maintenance_message = None
        self.maint_check_count = 0
        m = self.bot.metrics
        m.reports_in_progress.set_function(lambda: len(self.in_progress))
        bot.loop.create_task(self.startup_cleanup())

    def cog_unload(self):
        self.verify_empty_bug_queue.cancel()

    def can_mod(ctx):
        guild = Utils.BOT.get_guild(Configuration.get_var("guild_id"))
        member = guild.get_member(ctx.author.id)
        return member.guild_permissions.mute_members

    async def can_admin(ctx):
        return await ctx.bot.permission_manage_bot(ctx)

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
        # for name, cid in Configuration.get_var("channels").items():
        for row in BugReportingChannel.select():
            cid = row.channelid
            name = f"{row.platform.platform}_{row.platform.branch}"
            guild_id = row.guild.serverid
            channel = self.bot.get_channel(cid)

            message = await channel.send(Lang.get_locale_string("bugs/shutdown_message"))
            Configuration.set_persistent_var(f"{guild_id}_{name}_shutdown", message.id)

            # TODO: This is a migration that can be removed *after* it goes live the first time
            Configuration.del_persistent_var(f"{name}_shutdown", True)

    async def startup_cleanup(self):
        Logging.info("starting bugs")
        # TODO: find out what the condition is we need to wait for instead of just sleep
        # await asyncio.sleep(20)

        # for name, cid in Configuration.get_var("channels").items():
        reporting_channel_ids = []
        for row in BugReportingChannel.select():
            cid = row.channelid
            name = f"{row.platform.platform}_{row.platform.branch}"
            guild_id = row.guild.serverid
            channel = self.bot.get_channel(cid)

            # tolerate old persistent var key without guild_id.
            # TODO: This is a migration that can be removed *after* it goes live the first time
            shutdown_key = f"{name}_shutdown"
            shutdown_id = Configuration.get_persistent_var(shutdown_key)
            if shutdown_id is None:
                shutdown_key = f"{guild_id}_{name}_shutdown"
                shutdown_id = Configuration.get_persistent_var(shutdown_key)

            if shutdown_id is not None:
                try:
                    message = await channel.fetch_message(shutdown_id)
                    await message.delete()
                except (NotFound, HTTPException) as e:
                    pass
                Configuration.set_persistent_var(shutdown_key, None)
                reporting_channel_ids.append(cid)
        try:
            await self.send_bug_info(*reporting_channel_ids)
        except Exception as e:
            await Utils.handle_exception("bug startup failure", self.bot, e)

    async def send_bug_info(self, *args):
        for channel_id in args:
            channel = self.bot.get_channel(channel_id)
            bug_info_id = Configuration.get_persistent_var(f"{channel.guild.id}_{channel_id}_bug_message")

            ctx = None
            tries = 0
            while not ctx and tries < 5:
                tries += 1
                # this API call fails on startup because connection is not made yet.
                # TODO: properly wait for connection to be initialized
                try:
                    last_message = await channel.send('preparing bug reporting...')
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
                    Configuration.set_persistent_var(f"{channel.guild.id}_{channel_id}_bug_message", message.id)
                    Logging.info(f"Bug report message sent in channel #{channel.name} ({channel.id})")
                    await last_message.delete()
                except Exception as e:
                    # Ignore
                    await Utils.handle_exception(
                        f"Bug report message failed to send in channel #{channel.name} ({channel.id})", self.bot, e)
                    await asyncio.sleep(0.5)

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
        for guild in self.bot.guilds:
            try:
                # show/hide maintenance channel
                maint_message_channel = self.bot.get_guild_maintenance_channel(guild.id)
                if maint_message_channel is None:
                    message = f'maintenance channel is not configured for `{guild.name}`'
                    await self.bot.guild_log(guild.id, message)
                    await ctx.send(message)
                    continue

                default_role = ctx.guild.default_role
                channel_overwrite = maint_message_channel.overwrites[default_role]
                channel_overwrite.read_messages = active
                await maint_message_channel.set_permissions(default_role, overwrite=channel_overwrite)

                guild_config = self.bot.get_config(guild.id)
                beta_role = None
                if guild_config and guild_config.betarole:
                    beta_role = guild.get_role(guild_config.betarole)
                    beta_overwrite = maint_message_channel.overwrites[beta_role]
                    beta_overwrite.read_messages = active
                    await maint_message_channel.set_permissions(beta_role, overwrite=beta_overwrite)
                else:
                    message = f'beta role is not configured for `{guild.name}`'
                    await self.bot.guild_log(guild.id, message)
                    await ctx.send(message)

                for row in guild_config.bug_channels:
                    cid = row.channelid
                    branch = row.platform.branch

                    # show/hide reporting channels
                    channel = guild.get_channel(cid)

                    channel_overwrite = channel.overwrites[default_role]
                    channel_overwrite.read_messages = False if active else True
                    await channel.set_permissions(default_role, overwrite=channel_overwrite)

                    if re.search(r'beta', branch, re.I) and beta_role:
                        beta_overwrite = channel.overwrites[beta_role]
                        beta_overwrite.read_messages = False if active else True
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

    @bug.group(name='platforms', aliases=['platform'], invoke_without_command=True)
    @commands.check(can_admin)
    async def platforms(self, ctx):
        platforms = dict()

        for platform in BugReportingPlatform.select():
            if platform.branch in platforms:
                if platform.platform in platforms[platform.branch]:
                    await self.bot.guild_log(ctx.guild.id, f"duplicate platform in db: {platform.platform}/{platform.branch}")
            if platform.branch not in platforms:
                platforms[platform.branch] = list()
            platforms[platform.branch].append(platform.platform)

        embed = Embed(
            timestamp=ctx.message.created_at,
            color=0x50f3d7,
            title='Bug Reporting Platforms')

        for branch, platforms in platforms.items():
            embed.add_field(name=branch, value='\n'.join(platforms), inline=False)

        if not platforms:
            await ctx.send("There are no bug reporting platforms in my database")
        else:
            await ctx.send(embed=embed)

    @platforms.command(aliases=['add'])
    @commands.check(can_admin)
    async def add_platform(self, ctx,
                           platform: clean_content(remove_markdown=True),
                           branch: clean_content(remove_markdown=True)):
        row, create = BugReportingPlatform.get_or_create(platform=platform, branch=branch)
        if create:
            await ctx.send(f"Ok, I added `{platform}/{branch}` to my database")
        else:
            await ctx.send(f"That platform/branch combination is already in my database")

    @bug.group(name='channels', aliases=['channel'], invoke_without_command=True)
    @commands.guild_only()
    @commands.check(can_admin)
    async def channels(self, ctx):
        # TODO: allow guild admins to use this, restricted to single guild
        embed = Embed(
            timestamp=ctx.message.created_at,
            color=0x50f3d7,
            title='Bug Reporting Channels')
        guild_row = Guild.get_or_none(serverid=ctx.guild.id)
        guild_channels = []
        non_guild_channels = dict()
        for row in BugReportingPlatform.select():
            for channel_row in row.bug_channels:
                description = f"{row.platform}/{row.branch}: {self.bot.get_channel(channel_row.channelid).mention}"
                if channel_row.guild == guild_row:
                    guild_channels.append(description)
                else:
                    # TODO: get guild names and add to description
                    if channel_row.guild.serverid not in non_guild_channels:
                        non_guild_channels[channel_row.guild.serverid] = []
                    non_guild_channels[channel_row.guild.serverid].append(description)
        if guild_channels:
            embed.add_field(name=f'`{ctx.guild.name}` server', value="\n".join(guild_channels))
        for guild_id, channel_list in non_guild_channels.items():
            server_name = self.bot.get_guild(guild_id).name or guild_id
            embed.add_field(name=f'`{server_name}` server', value="\n".join(channel_list))
        if not guild_channels and not non_guild_channels:
            await ctx.send("There are no configured bug reporting channels")
        else:
            await ctx.send(embed=embed)

    @channels.command(aliases=['remove'])
    @commands.guild_only()
    @commands.check(can_admin)
    async def remove_channel(self, ctx, channel: TextChannel):
        try:
            row = BugReportingChannel.get(channelid=channel.id)
            platform = row.platform.platform
            branch = row.platform.branch
            row.delete_instance()
            await ctx.send(f"Removed `{platform}`/`{branch}`/{channel.mention} from my database")
        except DoesNotExist:
            await ctx.send(f"Could not find {channel.mention} in my database")

    @channels.command(aliases=['add'])
    @commands.guild_only()
    @commands.check(can_admin)
    async def add_channel(self, ctx,
                          channel: TextChannel,
                          platform: clean_content(remove_markdown=True),
                          branch: clean_content(remove_markdown=True)):
        try:
            guild_row = Guild.get(serverid=ctx.guild.id)
        except DoesNotExist:
            await ctx.send(f"I couldn't find a record for guild id {ctx.guild.id}... call a plumber!")
            return

        try:
            platform_row = BugReportingPlatform.get(platform=platform, branch=branch)
        except DoesNotExist:
            await ctx.send(f"I couldn't find a record for platform/branch `{platform}`/`{branch}`")
            return

        try:
            record, created = BugReportingChannel.get_or_create(guild=guild_row, platform=platform_row, channelid=channel.id)
        except IntegrityError:
            await ctx.send(f"channel{channel.mention} is already in used for bug reporting")
            return

        if created:
            await ctx.send(f"{channel.mention} will now be used to record `{platform}/{branch}` bug reports")
        else:
            await ctx.send(f"{channel.mention} was already configured for `{platform}/{branch}` bug reports")

        """
        "channels": {
            "android_beta": 622127033631113218,
            "android_stable": 622126928954130453,
            "ios_beta": 622127058113265665,
            "ios_stable": 622127005705437185
        },
        """

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
                await ctx.send(Lang.get_locale_string('bugs/reset_success', uid=uid))
            except Exception as e:
                await ctx.send(Lang.get_locale_string('bugs/reset_fail', uid=uid))
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
        guild = trigger_channel.guild
        member = guild.get_member(user.id)
        #mute_role = guild.get_role(Configuration.get_var("muted_role"))

        guild_config = self.bot.get_config(guild.id)
        mute_role = guild_config.mutedrole

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
                Logging.info(f"platform is {p}")
                platform = p

            def set_branch(b):
                nonlocal branch
                Logging.info(f"branch is {b}")
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

                report_id_saved = False
                attachment_id_saved = False
                user_reported_channels = list()
                all_reported_channels = list()
                selected_platform = BugReportingPlatform.get(platform=platform, branch=branch)

                for row in BugReportingChannel.select().where(BugReportingChannel.platform == selected_platform):
                    report_channel = self.bot.get_channel(row.channelid)
                    message = await report_channel.send(
                        content=Lang.get_locale_string("bugs/report_header", ctx, id=br.id, user=user.mention),
                        embed=report)
                    attachment = None
                    if len(attachment_links) != 0:
                        key = "attachment_info" if len(attachment_links) == 1 else "attachment_info_plural"
                        attachment = await report_channel.send(
                            Lang.get_locale_string(f"bugs/{key}", ctx, id=br.id, links="\n".join(attachment_links)))

                    if report_channel.guild.id == Configuration.get_var('guild_id'):
                        # Only save report and attachment IDs for posts in the official server
                        if not report_id_saved and not attachment_id_saved:
                            if attachment is not None:
                                br.attachment_message_id = attachment.id
                                attachment_id_saved = True
                            br.message_id = message.id
                            report_id_saved = True
                            br.save()
                            user_reported_channels.append(report_channel.mention)
                    else:
                        # guild is not the official server. if author is member, include user_reported_channels
                        this_guild = self.bot.get_guild(report_channel.guild.id)
                        if this_guild.get_member(user.id) is not None:
                            user_reported_channels.append(report_channel.mention)

                    all_reported_channels.append(report_channel)

                channels_mentions = []
                channels_ids = set()
                for report_channel in all_reported_channels:
                    channels_mentions.append(report_channel.mention)
                    channels_ids.add(report_channel.id)
                await channel.send(
                    Lang.get_locale_string("bugs/report_confirmation", ctx, channel_info=', '.join(channels_mentions)))
                await self.send_bug_info(*channels_ids)

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
                platforms = set()
                options = []
                for platform_row in BugReportingPlatform.select():
                    platforms.add(platform_row.platform)
                for platform_name in platforms:
                    options.append(
                        Questions.Option(
                            platform_name.upper(),
                            platform_name,
                            set_platform,
                            [platform_name]))
                Logging.info(options)
                await Questions.ask(self.bot, channel, user, Lang.get_locale_string("bugs/question_platform", ctx),
                                    options, show_embed=True, locale=ctx)
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
                branches = set()
                for platform_row in BugReportingPlatform.select():
                    branches.add(platform_row.branch)
                options = []
                for branch_name in branches:
                    options.append(
                        Questions.Option(
                            branch_name.upper(),
                            branch_name,
                            set_branch,
                            [branch_name]))
                await Questions.ask(self.bot, channel, user, Lang.get_locale_string("bugs/question_app_branch", ctx),
                                    options, show_embed=True, locale=ctx)
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
        except CancelledError as ex:
            m.report_incomplete_count.inc()
            if active_question is not None:
                m.reports_exit_question.observe(active_question)
            if not restarting:
                raise ex
        except Exception as ex:
            await Utils.handle_exception("bug reporting", self.bot, ex)
            raise ex
        finally:
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
                #  Consider letting user know why report didn't start?
                return
            await self.report_bug(user, channel)


def setup(bot):
    bot.add_cog(Bugs(bot))
