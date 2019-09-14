import asyncio

from discord import Forbidden, Embed, NotFound
from discord.ext.commands import Context, command

from cogs.BaseCog import BaseCog
from utils import Questions, Emoji, Utils, Configuration, Lang
from utils.Database import BugReport, Attachements


class Bugs(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())

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
        message = await channel.send(Lang.get_string("bug_info"))
        Configuration.set_persistent_var(f"{key}_message", message.id)

    @command()
    async def bug(self, ctx: Context):
        await self.report_bug(ctx.author, ctx.channel)

    async def report_bug(self, user, trigger_channel):
        # remove command to not flood chat (unless we are in a DM already)
        # if ctx.guild is not None:
        #     await ctx.message.delete()

        channel = await user.create_dm()

        # vars to store everything
        asking = True
        platform = ""
        branch = ""
        additional = False
        additional_text = ""
        attachments = False
        attachment_links = []
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
                return "Whoa there, i just need a version number, not an entire love letter."
            return True

        def max_length(length):
            def real_check(text):
                if len(text) > length:
                    return "That text seems suspiciously long for the question asked, please shorten it a bit"
                return True

            return real_check

        async def send_report():
            # save report in the database
            br = BugReport.create(reporter=user.id, platform=platform, platform_version=platform_version, branch=branch,
                                  app_version=app_version, title=title, steps=steps, expected=expected,
                                  additional=additional)
            for a in attachment_links:
                Attachements.create(report=br, url=a)

            # send report
            c = Configuration.get_var("channels")[f"{platform}_{branch}".lower()]
            message = await self.bot.get_channel(c).send(embed=report)
            br.message_id = message.id
            br.save()
            await channel.send(f"Your report was successfully send and can be found in <#{c}>!")

        async def restart():
            await self.report_bug(user, trigger_channel)

        try:

            await Questions.ask(self.bot, channel, user,
                                """You found a bug? Ouch, that's never fun. Next i will ask you some questions to help the devs look into it. For this i will need a few things:
- Device info like model and android/ios version (this can be found in device settings)
- Version of the Sky app, this can be found in ...
- Information about the bug itself, what you expected to happen, what really happened and how to make it happen.

If you don't know the info above like version numbers it is highly recommended to look it up before continuing.

Are you ready to proceed? 
""",  # TODO: can this be found in the app itself or need instructions per OS?
                                [
                                    Questions.Option("YES"),
                                    Questions.Option("NO", handler=abort),
                                ])
            if asking:
                # question 1: android or ios?
                await Questions.ask(self.bot, channel, user, "Are you using Android or iOS?",
                                    [
                                        Questions.Option("ANDROID", "Android", lambda: set_platform("Android")),
                                        Questions.Option("IOS", "iOS", lambda: set_platform("iOS"))
                                    ], show_embed=True)

                # question 2: android/ios version

                platform_version = await Questions.ask_text(self.bot, channel, user,
                                                            f"What {platform} version do you use?",
                                                            validator=verify_version)

                # question 3: stable or beta?
                await Questions.ask(self.bot, channel, user,
                                    "Are you using the stable version or a beta version? If you don't know what beta is you are probably using the stable version",
                                    [
                                        Questions.Option("STABLE", "Stable", lambda: set_branch("Stable")),
                                        Questions.Option("BETA", "Beta", lambda: set_branch("Beta"))
                                    ], show_embed=True)

                # question 4: sky app version
                app_version = await Questions.ask_text(self.bot, channel, user,
                                                       "What version of the sky app were you using when you experienced the bug?",
                                                       validator=verify_version)

                app_build = await Questions.ask_text(self.bot, channel, user,
                                                       "What build number of the sky app were you using?",
                                                       validator=verify_version)

                # question 5: short description
                title = await Questions.ask_text(self.bot, channel, user,
                                                 "Please describe describe your bug in a single sentece. This serves as a 'title' for your bug, you can add more detailed info in the questions after this one.",
                                                 validator=max_length(200))

                steps = await Questions.ask_text(self.bot, channel, user, """What steps do you need to take to triger the bug? Please specify them as below in a single message to improve readablity
- step 1
- step 2
- step 3""", validator=max_length(1024))

                expected = await Questions.ask_text(self.bot, channel, user,
                                                    "When following the steps above, what did you expect to happen?",
                                                    validator=max_length(100))

                await Questions.ask(self.bot, channel, user,
                                    "Do you have any **additional info** to add to this report?",
                                    [
                                        Questions.Option("YES", handler=add_additional),
                                        Questions.Option("NO")
                                    ])

                if additional:
                    additional_text = await Questions.ask_text(self.bot, channel, user,
                                                               "Please send the additional info to add to the report",
                                                               validator=max_length(500))

                await Questions.ask(self.bot, channel, user,
                                    "Do you have any **attachments** to add to this report?",
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
                report.add_field(name="Description & steps to reproduce", value=steps, inline=False)
                report.add_field(name="Expected outcome", value=expected)
                if additional:
                    report.add_field(name="Additional information", value=additional_text, inline=False)
                if attachments:
                    report.add_field(name="Attachment(s)", value="\n".join(attachment_links))

                # TODO: get bug id from database (latest id+1) and format so it's easy to search
                await channel.send(content=f"**Bug Report # {1} - submitted by {user.mention}**", embed=report)

                # TODO: detect video attachment and send it outside the embed
                # TODO: add formatted bug report ID to this message as well
                # txt = '**Attachment to report #12345**\n https://cdn.discordapp.com/attachments/620772242883739678/622203403115692052/Screenrecorder-2019-09-13-18-46-42-51800.mp4'
                # await channel.send(txt)

                await Questions.ask(self.bot, channel, user, "Does the above report look alright?",
                                    [
                                        Questions.Option("YES", "Yes, send this report", send_report),
                                        Questions.Option("NO", "Nope, i made a mistake. Start over", restart)
                                    ])


            else:
                return

        except Forbidden:
            await trigger_channel.send(
                "I was unable to DM you for questions about your bug, could you please (temp) allow DMs from this server and try again? You can enable this in the privacy settings, found in the server dropdown menu",
                delete_after=30)
        except asyncio.TimeoutError:
            pass


def setup(bot):
    bot.add_cog(Bugs(bot))
