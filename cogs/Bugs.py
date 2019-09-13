import asyncio

from discord import Forbidden
from discord.ext.commands import Context, command

from cogs.BaseCog import BaseCog
from utils import Questions, Emoji, Utils


class Bugs(BaseCog):
    @command()
    async def bug(self, ctx: Context):
        # remove command to not flood chat (unless we are in a DM already)
        if ctx.guild is not None:
            await ctx.message.delete()

        channel = await ctx.author.create_dm()

        # vars to store everything
        asking = True
        platform = ""
        branch = ""
        additional = False
        additional_text = ""
        attachments = False
        attachments_text = ""

        # define all the parts we need as inner functions for easier sinfulness

        async def abort():
            nonlocal asking
            await ctx.author.send(
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
            if len(v) > 50:
                return "Whoa there, i just need a version number, not an entire love letter."
            return True

        def max_length(length):
            def real_check(text):
                if len(text) > length:
                    return "That text seems suspiciously long for the question asked, please shorten it a bit"
                return True

            return real_check

        try:

            await Questions.ask(self.bot, channel, ctx.author,
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
                await Questions.ask(self.bot, channel, ctx.author, "Are you using Android or iOS?",
                                    [
                                        Questions.Option("ANDROID", "Android", lambda: set_platform("Android")),
                                        Questions.Option("IOS", "iOS", lambda: set_platform("iOS"))
                                    ], show_embed=True)

                # question 2: android/ios version

                platform_version = await Questions.ask_text(self.bot, channel, ctx.author,
                                                            f"What {platform} version do you use?",
                                                            validator=verify_version)

                # question 3: stable or beta?
                await Questions.ask(self.bot, channel, ctx.author,
                                    "Are you using the stable version or a beta version? If you don't know what beta is you are probably using the stable version",
                                    [
                                        Questions.Option("STABLE", "Stable", lambda: set_branch("Stable")),
                                        Questions.Option("BETA", "Beta", lambda: set_branch("Beta"))
                                    ], show_embed=True)

                # question 4: sky app version
                app_version = await Questions.ask_text(self.bot, channel, ctx.author,
                                                       "What version of the sky app where you using when you experienced the bug?",
                                                       validator=verify_version)

                # question 5: short description
                title = await Questions.ask_text(self.bot, channel, ctx.author,
                                                 "Please describe describe your bug in a single sentece. This serves as a 'title' for your bug, you can add more detailed info in the questions after this one.",
                                                 validator=max_length(200))

                steps = await Questions.ask_text(self.bot, channel, ctx.author, """What steps do you need to take to triger the bug? Please specify them as below in a single message to improve readablity
- step 1
- step 2
- step 3""", validator=max_length(1800))

                expected = await Questions.ask_text(self.bot, channel, ctx.author,
                                                    "When following the steps above, what did you expect to happen?",
                                                    validator=max_length(100))

                actual = await Questions.ask_text(self.bot, channel, ctx.author,
                                                  "When following the steps above, what happened instead?",
                                                  validator=max_length(100))

                await Questions.ask(self.bot, channel, ctx.author,
                                    "Do you have any **additional info** to add to this report?",
                                    [
                                        Questions.Option("YES", handler=add_additional),
                                        Questions.Option("NO")
                                    ])

                if additional:
                    additional_text = await Questions.ask_text(self.bot, channel, ctx.author,
                                                               "Please send the additional info to add to the report",
                                                               validator=max_length(500))

                await Questions.ask(self.bot, channel, ctx.author,
                                    "Do you have any **attachments** to add to this report?",
                                    [
                                        Questions.Option("YES", handler=add_attachments),
                                        Questions.Option("NO")
                                    ])

                if attachments:
                    attachments_text = await Questions.ask_attachements(self.bot, channel, ctx.author)

                await ctx.send(f"""
Platform: {platform}
{platform} version: {platform_version}
Branch: {branch}
App version: {app_version}
title: {title}
steps: {steps}
expected: {expected}
actual: {actual}
additional: {additional}
attachements: {attachments_text}
""")
            else:
                return

        except Forbidden:
            await ctx.send(
                "I was unable to DM you for questions about your bug, could you please (temp) allow DMs from this server and try again? You can enable this in the privacy settings, found in the server dropdown menu",
                delete_after=30)
        except asyncio.TimeoutError:
            pass


def setup(bot):
    bot.add_cog(Bugs(bot))
