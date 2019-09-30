import asyncio
import inspect
import re
from collections import namedtuple
from discord import Embed, Reaction
from utils import Emoji, Utils, Configuration, Lang

Option = namedtuple("Option", "emoji text handler", defaults=(None, None, None))

async def ask(bot, channel, author, text, options, timeout=60, show_embed=False, delete_after=False):
    embed = Embed(color=0x68a910, description='\n'.join(f"{Emoji.get_chat_emoji(option.emoji)} {option.text}" for option in options))
    message = await channel.send(text, embed=embed if show_embed else None)
    handlers = dict()
    for option in options:
        emoji = Emoji.get_emoji(option.emoji)
        await message.add_reaction(emoji)
        handlers[str(emoji)] = option.handler

    def check(reaction: Reaction, user):
        return user == author and str(reaction.emoji) in handlers.keys() and reaction.message.id == message.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=timeout, check=check)
    except asyncio.TimeoutError as ex:
        if delete_after:
            await message.delete()
        await channel.send(
            Lang.get_string("error_reaction_timeout", error_emoji=Emoji.get_emoji("WARNING"), timeout=timeout),
            delete_after=10 if delete_after else None)
        raise ex
    else:
        if delete_after:
            await message.delete()
        h = handlers[str(reaction.emoji)]
        if h is None:
            return
        if inspect.iscoroutinefunction(h):
            await h()
        else:
            h()


async def ask_text(
        bot,
        channel,
        user,
        text,
        validator=None,
        timeout=Configuration.get_var("question_timeout_seconds"),
        confirm=False):

    def check(message):
        return user == message.author and message.channel == channel

    ask_again = True

    def confirmed():
        nonlocal ask_again
        ask_again = False

    def clean_text(txt):
        """Remove multiple spaces and multiple newlines from input txt."""
        txt = re.sub(r' +', ' ', txt)
        txt = re.sub(r'\n\s*\n', '\n\n', txt)
        return txt

    while ask_again:
        message_cleaned = ""
        await channel.send(text)
        try:
            while True:
                message = await bot.wait_for('message', timeout=timeout, check=check)
                if message.content is None or message.content == "":
                    result = Lang.get_string("no_attachments")
                else:
                    message_cleaned = clean_text(message.content)
                    result = validator(message_cleaned) if validator is not None else True
                if result is True:
                    break
                else:
                    await channel.send(result)
        except asyncio.TimeoutError as ex:
            await channel.send(Lang.get_string("error_reaction_timeout", error_emoji=Emoji.get_emoji("WARNING"), timeout=timeout))
            raise ex
        else:
            content = Utils.escape_markdown(message_cleaned)
            if confirm:
                backticks = "``" if len(message_cleaned.splitlines()) is 1 else "```"
                message = f"Are you sure {backticks}{message_cleaned}{backticks} is correct?"
                await ask(bot, channel, user, message, [
                    Option("YES", handler=confirmed),
                    Option("NO")
                ])
            else:
                confirmed()

    return content


async def ask_attachements(
        bot,
        channel,
        user,
        timeout=Configuration.get_var("question_timeout_seconds"),
        max_files=Configuration.get_var('max_attachments')):

    def check(message):
        return user == message.author and message.channel == channel

    done = False

    def ready():
        nonlocal done
        done = True

    async def restart_attachments():
        nonlocal final_attachments
        final_attachments = []
        await ask(bot, channel, user, Lang.get_string("attachments_restart"), [
            Option("YES", "Yes, try adding attachments again"),
            Option("NO", "Do not attach any files", handler=ready)
        ], show_embed=True)

    while not done:
        ask_again = True
        final_attachments = []
        count = 0

        def confirmed():
            nonlocal ask_again
            ask_again = False

        while ask_again:
            if not final_attachments:
                await channel.send(Lang.get_string("attachment_prompt", max=max_files))
            elif len(final_attachments) < max_files - 1:
                await channel.send(Lang.get_string("attachment_prompt_continued", max=max_files - len(final_attachments)))
            elif len(final_attachments):
                await channel.send(Lang.get_string("attachment_prompt_final"))

            done = False

            try:
                while True:
                    message = await bot.wait_for('message', timeout=timeout, check=check)
                    links = Utils.URL_MATCHER.findall(message.content)
                    attachment_links = [str(a.url) for a in message.attachments]
                    if len(links) is not 0 or len(message.attachments) is not 0:
                        if (len(links) + len(message.attachments)) > max_files:
                            await channel.send(Lang.get_string("attachments_overflow", max=max_files))
                        else:
                            final_attachments += links + attachment_links
                            count += len(links) + len(attachment_links)
                            break
                    else:
                        await channel.send(Lang.get_string("attachment_not_found"))
            except asyncio.TimeoutError as ex:
                await channel.send(Lang.get_string("error_reaction_timeout", error_emoji=Emoji.get_emoji("WARNING"), timeout=timeout))
                raise ex
            else:
                if count < max_files:
                    await ask(bot, channel, user, "Do you want to add another attachment?",
                              [
                                  Option("YES"),
                                  Option("NO", handler=confirmed)
                              ])
                else:
                    ask_again = False

        await ask(bot, channel, user, f"Are those all the files you meant to send?", [
            Option("YES", Lang.get_string("approve_attachments"), handler=ready),
            Option("NO", f"Forget {'that attachment' if len(final_attachments) == 1 else 'those attachments'} and try again", handler=restart_attachments)
        ], show_embed=True)

    return final_attachments
