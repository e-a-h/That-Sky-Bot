import asyncio
from concurrent.futures import CancelledError
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
        message = await channel.send(Lang.get_string("bug_info"))
        bugemoji = Emoji.get_emoji('BUG')
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
        if user.id in self.in_progress:
            if user.id in self.canceling:
                await trigger_channel.send(f"{user.mention} stop spamming the bug reaction!", delete_after=10)
                return

            async def start_over():
                stop_cancel()
                self.in_progress[user.id].cancel()
                del self.in_progress[user.id]
                await self.report_bug(user, trigger_channel)

            def stop_cancel():
                self.canceling.remove(user.id)

            self.canceling.add(user.id)
            await Questions.ask(self.bot, trigger_channel, user, f"{user.mention} You are already in the middle of reporting a bug, do you want to cancel that report and start over?",
                                [
                                    Questions.Option("YES", handler=start_over),
                                    Questions.Option("NO", handler=stop_cancel)
                                ], delete_after=True)

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
            additional = False
            additional_text = ""
            attachments = False
            attachment_links = []
            attachment_message = ""
            report = None

            # define all the parts we need as inner functions for easier sinfulness

            async def abort():
                nonlocal asking
                await user.send(
                    "No? Alright then, the devs won't be able to look into it but feel free to return later to report it then!")
                asking = False

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
                    return "Please specify a version number, ``latest`` is not valid because what is latest changes overtime. You can also think you have latest but a newer update might be available if you didn't check recently"
                # TODO: double check if we actually want to enforce this
                if len(Utils.NUMBER_MATCHER.findall(v)) is 0:
                    return "There don't appear to be any numbers in there"
                if len(v) > 20:
                    return "Whoa there, I just need a version number, not an entire love letter."
                return True

            def max_length(length):
                def real_check(text):
                    if len(text) > length:
                        return "That text seems suspiciously long for the question asked, Try typing up a shorter answer and we'll see if I like it"
                    return True

                return real_check

            async def send_report():
                # save report in the database
                br = BugReport.create(reporter=user.id, platform=platform, platform_version=platform_version,
                                      branch=branch, app_version=app_version, title=title, steps=steps,
                                      expected=expected, additional=additional_text)
                for url in attachment_links:
                    Attachements.create(report=br, url=url)

                # send report
                channel_name = f"{platform}_{branch}".lower()
                c = Configuration.get_var("channels")[channel_name]
                message = await self.bot.get_channel(c).send(
                    content=f"**Bug Report {br.id} - submitted by {user.mention}**", embed=report)
                if attachment_message:
                    attachment = await self.bot.get_channel(c).send(f"**Attachment to report {br.id}**\n{attachment_message}")
                    br.attachment_message_id = attachment.id
                br.message_id = message.id
                br.save()
                await channel.send(f"Thank you! Your report was successfully sent and can be found in <#{c}>!")
                await self.send_bug_info(channel_name)

            async def restart():
                del self.in_progress[user.id]
                await self.report_bug(user, trigger_channel)

            await Questions.ask(self.bot, channel, user,
                                """```css
Report a Bug```
Help me collect the following information. It will be *very helpful* in identifying, reproducing, and fixing bugs:
- Device type
- Operating System Version
- Sky App Type
- Version of the Sky app
- Description of the problem, and how to reproduce it
- Additional Information
- Attachment(s)

Ready to get started?
""",  # TODO: can this be found in the app itself or need instructions per OS?
                                [
                                    Questions.Option("YES"),
                                    Questions.Option("NO", handler=abort),
                                ])
            if asking:
                # question 1: android or ios?
                await Questions.ask(self.bot, channel, user, """```css
Device Type```
Are you using Android or iOS?
""",
                                    [
                                        Questions.Option("ANDROID", "Android", lambda: set_platform("Android")),
                                        Questions.Option("IOS", "iOS", lambda: set_platform("iOS"))
                                    ], show_embed=True)

                # question 2: android/ios version
                platform_version = await Questions.ask_text(self.bot, channel, user, f"""```css
Operating System Version```
What {platform} version do you use? This can be found in device settings.
""",
                                                            validator=verify_version)

                # question 3: stable or beta?
                await Questions.ask(self.bot, channel, user, f"""```css
Sky App Type```
Are you using the Live game or a Beta version? The beta version is installed through TestFlight on iOS or Google Groups on Android. If you are unsure, then choose the Live version.
""",
                                    [
                                        Questions.Option("STABLE", "Live", lambda: set_branch("Stable")),
                                        Questions.Option("BETA", "Beta", lambda: set_branch("Beta"))
                                    ], show_embed=True)

                # question 4: sky app version
                app_version = await Questions.ask_text(self.bot, channel, user, """```css
Sky App Version Number```
What **version** of the sky app where you using when you experienced the bug?
# TODO: instructions
""", validator=verify_version)

                #question 5: sky app build number
                app_build = await Questions.ask_text(self.bot, channel, user, """```css
Sky App Build Number```
What **build** of the sky app where you using when you experienced the bug?
# TODO: instructions
""", validator=verify_version)

                # question 6: Title
                title = await Questions.ask_text(self.bot, channel, user, """```css
Title/Topic
```
Provide a brief title or topic for your bug.
""", validator=max_length(100))

                # question 7: "actual" - defect behavior
                actual = await Questions.ask_text(self.bot, channel, user,"""```css
Describe the bug
```
Describe the problem you experienced, what looked or worked the wrong way. I'll ask for steps to reproduce the problem next, so don't tell me *how* it happened yet."
""", validator=max_length(400))

                # question 8: steps to reproduce
                steps = await Questions.ask_text(self.bot, channel, user, """```css
How to Reproduce the Bug```
How did the bug occur? Provide steps that will help us reproduce the problem. Example:
```- step 1
- step 2
- step 3```
""", validator=max_length(800))

                # question 9: expected behavior
                expected = await Questions.ask_text(self.bot, channel, user, """```css
Expectation
``` 
When following the steps above, what did you expect to happen?
""", validator=max_length(200))

                # question 10: additional info
                await Questions.ask(self.bot, channel, user, """```css
Additional Information
``` 
Do you have any additional info to add to this report?""",
                                    [
                                        Questions.Option("YES", handler=add_additional),
                                        Questions.Option("NO")
                                    ])

                if additional:
                    additional_text = await Questions.ask_text(self.bot, channel, user,
                                                               "Please send the additional info to add to the report",
                                                               validator=max_length(500))

                #question 11: attachments
                await Questions.ask(self.bot, channel, user, """```css
Attachments
``` 
Do you have any attachments to add to this report?""",
                                    [
                                        Questions.Option("YES", handler=add_attachments),
                                        Questions.Option("NO")
                                    ])

                if attachments:
                    attachment_links = await Questions.ask_attachements(self.bot, channel, user)

                # assemble the report
                report = Embed()
                report.set_author(name=f"{user} ({user.id})", icon_url=user.avatar_url_as(size=32))
                report.add_field(name="Platform", value=f"{platform} {platform_version}")
                report.add_field(name="Sky app version", value=app_version)
                report.add_field(name="Sky app build", value=app_build)
                report.add_field(name="Title/Topic", value=title, inline=False)
                report.add_field(name="Bug description", value=actual, inline=False)
                report.add_field(name="Steps to reproduce", value=steps, inline=False)
                report.add_field(name="Expected outcome", value=expected)
                if additional:
                    report.add_field(name="Additional information", value=additional_text, inline=False)

                await channel.send(content=f"**Bug Report ## - submitted by {user.mention}**", embed=report)
                if attachment_links:
                    attachment_message = ''
                    for a in attachment_links:
                        attachment_message += f"{a}\n"
                    await channel.send(attachment_message)
                await Questions.ask(self.bot, channel, user, "This is the information you have provided. Submit this report, or discard it?",
                                    [
                                        Questions.Option("YES", "Yes, send this report", send_report),
                                        Questions.Option("NO", "Nope, i made a mistake. Start over", restart)
                                    ])
            else:
                return

        except Forbidden:
            await trigger_channel.send(
                f"{user.mention}, I was unable to DM you for questions about your bug, Please allow DMs from this server to file bug reports. You can enable this in the privacy settings, found in the server dropdown menu. Once your report is filed, you may disable DMs again if you like.",
                delete_after=30)
        except (asyncio.TimeoutError, CancelledError):
            del self.in_progress[user.id]
        except Exception as ex:
            del self.in_progress[user.id]
            await Utils.handle_exception("bug reporting", self.bot, ex)
            raise ex
        else:
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
