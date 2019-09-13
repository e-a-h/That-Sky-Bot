import asyncio
import inspect
from collections import namedtuple

from discord import Embed, Reaction

from utils import Emoji, Utils

Option = namedtuple("Option", "emoji text handler", defaults=(None, None, None))


async def ask(bot, channel, author, text, options, timeout=60, show_embed=False):
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
        await channel.send(f"🚫 Got no reaction within {timeout} seconds, aborting")
        raise ex
    else:
        h = handlers[str(reaction.emoji)]
        if h is None:
            return
        if inspect.iscoroutinefunction(h):
            await h()
        else:
            h()


async def ask_text(bot, channel, user, text, validator=None, timeout=300, confirm=True):

    def check(message):
        return user == message.author and message.channel == channel

    ask_again = True

    def confirmed():
        nonlocal ask_again
        ask_again = False

    while ask_again:
        await channel.send(text)
        try:
            while True:
                message = await bot.wait_for('message', timeout=timeout, check=check)
                result = validator(message.content) if validator is not None else True
                if result is True:
                    break
                else:
                    await channel.send(result)
        except asyncio.TimeoutError as ex:
            await channel.send(f"🚫 Got no reaction within {timeout} seconds, aborting")
            raise ex
        else:
            content = Utils.escape_markdown(message.content)
            if confirm:
                message = f"Are you sure ``{message.content}`` is correct?" if len(message.content.splitlines()) is 1 else f"Are you sure ```{message.content}``` is correct?"
                await ask(bot, channel, user, message, [
                    Option("YES", handler=confirmed),
                    Option("NO")
                ])

    return content



async def ask_attachements(bot, channel, user, timeout=300, confirm=True, max=3):
    def check(message):
        return user == message.author and message.channel == channel

    done = False

    def ready():
        nonlocal done
        done = True

    while not done:
        ask_again = True
        final_attachments = ""
        count = 0

        def confirmed():
            nonlocal ask_again
            ask_again = False

        while ask_again:
            await channel.send("Please send your attachment(s)")
            done = False

            try:
                while True:
                    message = await bot.wait_for('message', timeout=timeout, check=check)
                    links = Utils.URL_MATCHER.findall(message.content)
                    link_text = "\n".join(links)
                    attachment_links = "\n".join(str(a.url) for a in message.attachments)
                    if len(links) is not 0 or len(message.attachments) is not 0:
                        if (len(links) + len(message.attachments)) > 3:
                            await channel.send("You can only add up to 3 attachments")
                        else:
                            final_attachments += f"{link_text}\n{attachment_links}"
                            count += len(links) + len(attachment_links)
                            break
                    else:
                        await channel.send("Unable to find any attachments in that message")
            except asyncio.TimeoutError as ex:
                await channel.send(f"🚫 Got no reaction within {timeout} seconds, aborting")
                raise ex
            else:
                if count < max:
                    await ask(bot, channel, user, "Do you want to add another attachment?",
                              [
                                  Option("YES"),
                                  Option("NO", handler=confirmed)
                              ])
                else:
                    ask_again = False


        await ask(bot, channel, user, f"Are you sure you want to attach those links?", [
            Option("YES", handler=ready),
            Option("NO")
        ])

    return final_attachments