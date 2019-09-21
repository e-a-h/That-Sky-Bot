import asyncio
import time
from concurrent.futures import CancelledError
from datetime import datetime

from discord import Forbidden, Embed, NotFound
from discord.ext import commands
from discord.ext.commands import Context, command
from cogs.BaseCog import BaseCog
from utils import Questions, Emoji, Utils, Configuration, Lang
from utils.Database import BugReport, Attachements


class Bugs(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())
        self.bug_messages = set()
        self.in_progress = dict()
        self.canceling = set()

    async def shutdown(self):
        for name, cid in Configuration.get_var("channels").items():
            channel = self.bot.get_channel(cid)
            message = await channel.send(Lang.get_string("shutdown_message"))
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
        message = await channel.send(Lang.get_string("bug_info", bug_emoji=bugemoji))
        await message.add_reaction(bugemoji)
        self.bug_messages.add(message.id)
        Configuration.set_persistent_var(f"{key}_message", message.id)

    @command()
    async def bug(self, ctx: Context):
        # remove command to not flood chat (unless we are in a DM already)
        if ctx.guild is not None:
            await ctx.message.delete()
        await self.report_bug(ctx.author, ctx.channel)

    async def report_bug(self, user, trigger_channel):
        # fully ignore muted users
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
            if user.id in self.canceling:
                await trigger_channel.send(Lang.get_string("stop_spamming", user=user.mention), delete_after=10)
                return

            should_reset = False

            async def start_over():
                nonlocal should_reset
                should_reset = True

                if user.id in self.canceling:
                    self.canceling.remove(user.id)

            self.canceling.add(user.id)
            await Questions.ask(self.bot, trigger_channel, user, Lang.get_string("start_over", user=user.mention),
                                [
                                    Questions.Option("YES", handler=start_over),
                                    Questions.Option("NO")
                                ], delete_after=True)
            if user.id in self.canceling:
                self.canceling.remove(user.id)

            if should_reset:
                self.in_progress[user.id].cancel()
                del self.in_progress[user.id]
            else:
                return
        task = self.bot.loop.create_task(self.actual_bug_reporter(user, trigger_channel))
        self.in_progress[user.id] = task

    async def actual_bug_reporter(self, user, trigger_channel):
        # wrap everything so users can't get stuck in limbo
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
            attachment_message = ""
            report = None

            # define all the parts we need as inner functions for easier sinfulness

            async def abort():
                nonlocal asking
                await user.send(Lang.get_string("abort_report"))
                asking = False
                if user.id in self.in_progress:
                    del self.in_progress[user.id]

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
                    return Lang.get_string("latest_not_allowed")
                # TODO: double check if we actually want to enforce this
                if len(Utils.NUMBER_MATCHER.findall(v)) is 0:
                    return Lang.get_string("no_numbers")
                if len(v) > 20:
                    return Lang.get_string("love_letter")
                return True

            def max_length(length):
                def real_check(text):
                    if len(text) > length:
                        return Lang.get_string("text_too_long", max=length)
                    return True

                return real_check

            async def send_report():
                # save report in the database
                br = BugReport.create(reporter=user.id, platform=platform, deviceinfo=deviceinfo,
                                      platform_version=platform_version, branch=branch, app_version=app_version,
                                      app_build=app_build, title=title, steps=steps, expected=expected, actual=actual,
                                      additional=additional_text)
                for url in attachment_links:
                    Attachements.create(report=br, url=url)

                # send report
                channel_name = f"{platform}_{branch}".lower()
                c = Configuration.get_var("channels")[channel_name]
                message = await self.bot.get_channel(c).send(
                    content=Lang.get_string("report_header", id=br.id, user=user.mention), embed=report)
                if len(attachment_links) is not 0:
                    key = "attachment_info" if len(attachment_links) is 1 else "attachment_info_plural"
                    attachment = await self.bot.get_channel(c).send(
                        Lang.get_string(key, id=br.id, links="\n".join(attachment_links)))
                    br.attachment_message_id = attachment.id
                br.message_id = message.id
                br.save()
                await channel.send(Lang.get_string("report_confirmation", channel_id=c))
                await self.send_bug_info(channel_name)

            async def restart():
                del self.in_progress[user.id]
                await self.report_bug(user, trigger_channel)

            await Questions.ask(self.bot, channel, user, Lang.get_string("question_ready"),
                                [
                                    Questions.Option("YES"),
                                    Questions.Option("NO", handler=abort),
                                ])
            if asking:
                # question 1: android or ios?
                await Questions.ask(self.bot, channel, user, Lang.get_string("question_platform"),
                                    [
                                        Questions.Option("ANDROID", "Android", lambda: set_platform("Android")),
                                        Questions.Option("IOS", "iOS", lambda: set_platform("iOS"))
                                    ], show_embed=True)

                # question 2: android/ios version
                platform_version = await Questions.ask_text(self.bot, channel, user,
                                                            Lang.get_string("question_platform_version",
                                                                            platform=platform),
                                                            validator=verify_version)

                # question 3: hardware info
                deviceinfo = await Questions.ask_text(self.bot, channel, user, Lang.get_string("question_device_info", platform=platform, max=100), validator=max_length(100))

                # question 4: stable or beta?
                await Questions.ask(self.bot, channel, user, Lang.get_string("question_app_branch"),
                                    [
                                        Questions.Option("STABLE", "Live", lambda: set_branch("Stable")),
                                        Questions.Option("BETA", "Beta", lambda: set_branch("Beta"))
                                    ], show_embed=True)


                # TODO: remove me when android goes live
                if branch == "Stable" and platform == "Android":
                    await channel.send(Lang.get_string("no_live_android"))
                    return

                # question 5: sky app version
                app_version = await Questions.ask_text(self.bot,
                                                       channel,
                                                       user,
                                                       Lang.get_string(
                                                           "question_app_version",
                                                           version_help=Lang.get_string("version_" + platform.lower())),
                                                       validator=verify_version)

                # question 6: sky app build number
                app_build = await Questions.ask_text(self.bot, channel, user, Lang.get_string("question_app_build"),
                                                     validator=verify_version)

                # question 7: Title
                title = await Questions.ask_text(self.bot, channel, user, Lang.get_string("question_title", max=100),
                                                 validator=max_length(100))

                # question 8: "actual" - defect behavior
                actual = await Questions.ask_text(self.bot, channel, user, Lang.get_string("question_actual", max=400),
                                                  validator=max_length(400))

                # question 9: steps to reproduce
                steps = await Questions.ask_text(self.bot, channel, user, Lang.get_string("question_steps", max=800),
                                                 validator=max_length(800))

                # question 10: expected behavior
                expected = await Questions.ask_text(self.bot, channel, user,
                                                    Lang.get_string("question_expected", max=200),
                                                    validator=max_length(200))

                # question 11: attachments
                await Questions.ask(self.bot, channel, user, Lang.get_string("question_attachments"),
                                    [
                                        Questions.Option("YES", handler=add_attachments),
                                        Questions.Option("NO")
                                    ])

                if attachments:
                    attachment_links = await Questions.ask_attachements(self.bot, channel, user)

                # question 12: additional info
                await Questions.ask(self.bot, channel, user, Lang.get_string("question_additional"),
                                    [
                                        Questions.Option("YES", handler=add_additional),
                                        Questions.Option("NO")
                                    ])

                if additional:
                    additional_text = await Questions.ask_text(self.bot, channel, user,
                                                               Lang.get_string("question_additional_info"),
                                                               validator=max_length(500))

                # assemble the report
                report = Embed(timestamp=datetime.utcfromtimestamp(time.time()))
                report.set_author(name=f"{user} ({user.id})", icon_url=user.avatar_url_as(size=32))
                report.add_field(name=Lang.get_string("platform"), value=f"{platform} {platform_version}")
                report.add_field(name=Lang.get_string("app_version"), value=app_version)
                report.add_field(name=Lang.get_string("app_build"), value=app_build)
                report.add_field(name=Lang.get_string("device_info"), value=deviceinfo, inline=False)
                report.add_field(name=Lang.get_string("title"), value=title, inline=False)
                report.add_field(name=Lang.get_string("description"), value=actual, inline=False)
                report.add_field(name=Lang.get_string("str"), value=steps, inline=False)
                report.add_field(name=Lang.get_string("expected"), value=expected)
                if additional:
                    report.add_field(name=Lang.get_string("additional_info"), value=additional_text, inline=False)

                await channel.send(content=Lang.get_string("report_header", id="##", user=user.mention), embed=report)
                if attachment_links:
                    attachment_message = ''
                    for a in attachment_links:
                        attachment_message += f"{a}\n"
                    await channel.send(attachment_message)
                await Questions.ask(self.bot, channel, user,
                                    Lang.get_string("question_ok"),
                                    [
                                        Questions.Option("YES", Lang.get_string("send_report"), send_report),
                                        Questions.Option("NO", Lang.get_string("mistake"), restart)
                                    ])
            else:
                return

        except Forbidden:
            await trigger_channel.send(
                Lang.get_string("dm_unable", user=user.mention),
                delete_after=30)
        except (asyncio.TimeoutError, CancelledError):
            if user.id in self.in_progress:
                del self.in_progress[user.id]
        except Exception as ex:
            if user.id in self.in_progress:
                del self.in_progress[user.id]
            await Utils.handle_exception("bug reporting", self.bot, ex)
            raise ex
        else:
            if user.id in self.in_progress:
                del self.in_progress[user.id]

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
