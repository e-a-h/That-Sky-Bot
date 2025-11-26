"""
A module for managing interactions with Discord users in a dropbox-style feedback system.

This module implements Discord UI components, follow-up systems, and user interaction
management for a feedback and reporting system. It allows users to submit reports through
Discord modals, handles follow-up messages, and provides functionality for managing user
locks to prevent spamming or duplicate submissions.

Classes
-------
DropboxFollowup
    A class for storing follow-up details for interactions with users in the dropbox system.

DropModal
    A Discord UI Modal for user inputs, such as feedback or reports.

DropboxButton
    A dynamic Discord UI Button designed to trigger and manage user interactions with a
    specific dropbox target.

Functions
---------
unlock_user
    Unlocks a user by user ID, removing restrictions for new feedback submissions.

followup_finally
    Handles final steps and cleanup actions for follow-up interactions in the dropbox system.

followup_forwarding_done
    Sends a completion message to the user and acknowledges forwarding completion.

followup_forwarding_interrupt
    Interrupts an ongoing dropbox follow-up operation, with confirmation from the user.

followup_forwarding_expire
    Handles expiration of the follow-up session, releasing user locks and cleaning up messages.
"""
import asyncio
import io
import re
import traceback
from asyncio import CancelledError
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from itertools import islice
from typing import Dict, Set, Union, Optional, Tuple

import aiohttp
import discord
from discord import (Embed, NotFound, HTTPException, Message, TextChannel, User, Interaction,
                     Permissions, ButtonStyle, app_commands, AllowedMentions)
from discord.abc import Messageable
from discord.app_commands import Group, Choice
from discord.ext import commands, tasks
from discord.ext.commands import Context
from tortoise.exceptions import OperationalError, MultipleObjectsReturned, DoesNotExist

from cogs.BaseCog import BaseCog
from utils import Lang, Questions, Utils, Logging, Constants, UserActionRegister
from utils.Database import DropboxChannel, DropboxView, DropboxTarget, DropboxThreadMode
from utils.Emoji import get_chat_emoji
from utils.Helper import Sender, ConfirmView
from utils.UserActionRegister import is_user_registered, get_user_action, StopUserActionButton, UserActionItem
from utils.Utils import interaction_response as ir, paginate, get_prefix


####################
# Module classes
####################

user_locks: Dict[int, datetime] = {}
followup_timeout_seconds: int = 30
user_lock_seconds: int = 300
modal_subject_max_length: int = 100
modal_body_max_length: int = 4000
confirm_view_timeout: float = 30.0
subject_max_length = 100
preview_length = 500
page_size = 1800


@dataclass
class DropboxFollowup:
    """
    A follow-up interaction within a specified communication channel.

    This class represents a system to manage and track follow-up interactions
    in a specific channel. It provides attributes to record the context of an
    interaction, the target channel for communication, the timestamp of creation,
    and optionally, the most recent message in the interaction. It also provides
    metadata to associate an action registration name.

    Attributes
    ----------
    interaction : Interaction
        The interaction context corresponding to the follow-up.
    target_channel : Messageable
        The communication channel where the follow-up occurs.
    created_at : datetime
        The timestamp indicating when the follow-up was created.
    last_message : Message, optional
        The most recent message associated with the follow-up.
    action_register_name : str
        The associated action registration name.
    """
    interaction: Interaction
    target_channel: Messageable
    created_at: datetime
    last_message: Message = None
    action_register_name = "listen_for_followup"


class DropModal(discord.ui.Modal):
    """
    A modal dialog for user submissions with specific input fields and target configuration.

    This class represents a modal dialog, designed for collecting structured user input and delivering it to a
    specified target channel. It supports adjustable fields such as subject and message body with configurable label,
    placeholder text, and maximum input length.

    Attributes
    ----------
    target : DropboxTarget
        The target configuration object defining where and how the user input should be processed.
    title : str
        The title displayed on the modal dialog.
    label : str
        The label text for one of the input fields.
    placeholder : str
        Placeholder description within the user input field.
    target_channel : discord.abc.GuildChannel
        The Discord text channel where the processed user submission will be directed.
    """
    def __init__(self, target: DropboxTarget) -> None:
        super().__init__(title=target.modal_title)
        self.target: DropboxTarget = target
        self.title = target.modal_title
        self.label = target.modal_label
        self.placeholder = target.modal_placeholder
        self.target_channel = Utils.BOT.get_channel(target.channelid)
        # TODO: configurable text field length?

        self.add_item(discord.ui.TextInput(
            label="Subject",
            placeholder="Subject",
            required=False,
            style=discord.TextStyle.short,
            max_length=modal_subject_max_length))

        self.add_item(discord.ui.TextInput(
            label=target.modal_label,
            placeholder=self.placeholder,
            style=discord.TextStyle.long,
            max_length=modal_body_max_length))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_locks[interaction.user.id] = datetime.now(timezone.utc)
            await ir(interaction).defer(ephemeral=True)

            subject = str(self.children[0].value).strip("#\u200B \n")
            message = str(self.children[1].value).strip("\u200B \n")
            message = re.sub(r"\n\n+", "\n\n", message)
        except Exception as e:
            Logging.error(e, exc_info=True)
        else:
            drop_msg, thread_opened = await drop_to_target(interaction, self.target, subject, message)
            delivered = drop_msg is not None
            await send_receipt(interaction, drop_msg, self.target, subject, message, delivered, thread_opened)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        sender = Sender(interaction)
        await sender.send(
            'Oops! Something went wrong.', ephemeral=True)
        Logging.error("".join(traceback.format_tb(error.__traceback__)))

class DropboxButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r'dropboxtarget:(?P<id>[0-9]+)'):
    """
    Represents a button in a Discord UI that interacts with a dropbox target.

    A class for managing a UI component that interact with a specific dropbox target.

    Attributes
    ----------
    target : DropboxTarget or None
        The dropbox target associated with the button. If None, the button is considered disabled.
    """

    def __init__(self, target: DropboxTarget) -> None:
        if target is None:
            # A defunct view was triggered. Placeholder will not respond.
            super().__init__(
                discord.ui.Button(
                    style=discord.ButtonStyle.secondary,
                    label="disabled",
                    custom_id=f'dropboxtarget:0'))
        else:
            super().__init__(
                discord.ui.Button(
                    label=target.button_label,
                    style=ButtonStyle(target.button_style),
                    emoji=target.button_emoji,
                    custom_id=f'dropboxtarget:{target.id}'))
        self.target = target

    # This is called when the button is clicked and the custom_id matches the template.
    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        target_id = int(match['id'])
        # my_target = await DropboxTarget.get_or_none(id=target_id)
        try:
            target = await DropboxTarget.get(id=target_id)
        except DoesNotExist:
            target = None
        return cls(target)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id in user_locks:
            await ir(interaction).send_message(
                f"You recently started a report. Check your DMs to ensure your "
                f"report is complete. If you don't have an active report, try again later.",
                ephemeral=True)
            return
        if self.target is None:
            await ir(interaction).send_message("The button you pressed has been disabled.", ephemeral=True)
            await Utils.guild_log(
                interaction.guild_id,
                f"There's a broken dropbox button in {interaction.channel.mention}. Delete the message!"
                f" If there are still active buttons, create the controls again with `/dropbox prepare_channel`")
            return
        await ir(interaction).send_modal(DropModal(self.target))


####################
# Module functions
####################

def unlock_user(user_id: int) -> None:
    if user_id in user_locks:
        del user_locks[user_id]


async def followup_finally(interaction: Optional[Interaction], item: UserActionItem):
    Logging.debug(f"finally item: {item}")
    my_data: DropboxFollowup = item.data or None
    if my_data:
        await my_data.target_channel.send(
            f"__**Followup {'Expired' if interaction is None else 'Complete'}** - "
            f"DM with {'user' if interaction is None else interaction.user.mention} closed__",
            allowed_mentions=AllowedMentions.none())

async def followup_forwarding_done(interaction: Interaction, item: UserActionItem):
    unlock_user(interaction.user.id)
    sender = Sender(interaction)
    await sender.send("Done forwarding. Bye!")

async def followup_forwarding_interrupt(interaction: Interaction, item: UserActionItem) -> bool:
    """
    callback for interrupting dropbox dm followup operation
    Parameters
    ----------
    interaction
    item

    Returns
    -------
    bool
    """
    msg = ("You have a report/feedback in progress in DMs. If you continue, "
           "I will stop forwarding additional messages or attachments from DMs. "
           "If you cancel this request, you can return to DMs and continue "
           "sending messages for me to forward.")
    view = ConfirmView(interaction.user)
    await interaction.followup.send(msg, view=view, ephemeral=True)
    await view.wait()

    if view.value is None:
        await interaction.followup.send(
            Lang.get_locale_string('common/interaction_timeout', interaction, description="interrupt followup"),
            ephemeral=True)
        return False

    if view.value:
        # quietly allow cancellation. assume new interaction will take up messaging
        return True

    await interaction.followup.send(
        f"Ok, I won't cancel your existing report. "
        f"[Return to DMs to continue]({interaction.user.dm_channel.jump_url}).",
        ephemeral=True)

    return False


async def followup_forwarding_expire(item: UserActionItem):
    followup: DropboxFollowup = item.data
    if followup is None:
        return
    Logging.debug(f"followup expired: {followup}")
    unlock_user(followup.interaction.user.id)
    try:
        await followup.last_message.delete()
    except:
        pass
    try:
        await followup.interaction.user.send(
            f"Followup time for the request you started in {followup.interaction.channel.mention} "
            f"has expired. I will no longer forward additional messages. "
            f"If you would like to send more, start again.\n"
            f"-# If you finished a long time ago and I'm bothering you, "
            f"remember to press the `done` button next time! \N{LOVE LETTER}")
    except Exception as e:
        Logging.info(f"followup expiration message failed to send to {followup.interaction.user.id}: {e}")


def prepare_author_embed(user: User):
    # the embed to display who was the author in dropbox channel
    try:
        avatar = user.avatar.replace(size=32) if user.avatar else None
        embed = Embed(timestamp=datetime.now(timezone.utc), color=0x663399)
        embed.set_author(name=f"{user.name} ({user.id})", icon_url=avatar)
        embed.add_field(name="Author link", value=user.mention)
    except Exception as e:
        Logging.error(e, exc_info=True)
        raise
    return embed


def get_thread_name(author_name, subject, message) -> str:
    """
    Generate a thread name based on the author, subject, and message content.

    The function constructs a unique thread name combining the author's name and
    the subject if available. If the subject is not available, a portion of the
    message content is used instead. Whitespace and header markdown is removed.
    The final thread name is truncated to a predefined maximum length.

    Parameters
    ----------
    author_name : str
        The name of the author of the message.
    subject : str
        The subject of the message. If not empty, it is used in the thread name
        construction.
    message : str
        The body of the message, used as a fallback if the subject is empty.

    Returns
    -------
    str
        A sanitized, truncated thread name combining the author's name and either
        the subject or a portion of the message content.
    """
    if len(subject) > 0:
        my_name = subject
    else:
        my_name = message[:subject_max_length]

    my_name = re.sub(r"[\n#]", " ", my_name)  # remove newlines and header markdown
    my_name = re.sub(r"[\s\u200B]{2,}", " ", my_name)  # collapse multiple whitespace
    my_name = f"{author_name}: {my_name}"[:subject_max_length]
    return my_name


async def open_thread(source_message, author_name, subject, message):
    try:
        thread_name = get_thread_name(author_name, subject, message)
        target_channel = await source_message.create_thread(
            name=thread_name,
            auto_archive_duration=Constants.THREAD_AUTO_ARCHIVE_DURATION_MAX,
            reason=thread_name)
        return target_channel
    except Exception as e:
        Logging.error(f"Thread creation failed {e}\nMessage:\n\t{message}", exc_info=True)
        raise e


def author_info(user: User, mention: bool = False):
    return f"{user.mention if mention else user.display_name} [{user.name}]({user.id})"

async def drop_to_target(
        interaction: discord.Interaction,
        target: DropboxTarget,
        subject: str,
        message: str) -> Tuple[Optional[discord.Message], bool]:
    """
    Perform the forwarding of dropped messages, threading in a target channel, and request for DM

    Parameters
    ----------
    interaction
    target
    subject
    message

    Returns
    -------
    Channel
        Either dropbox target channel or thread
    """
    messages_to_channel = []
    messages_to_thread = []
    target_channel = Utils.BOT.get_channel(target.channelid)
    author_name = author_info(interaction.user, False)
    author_name_mention = author_info(interaction.user, True)

    if len(subject) > 0:
        message = f"## {subject}\n{message}"
    message = f"{author_name_mention}\n{message}"

    threaded = ((target.thread_mode == DropboxThreadMode.always) or
                (target.thread_mode == DropboxThreadMode.auto and
                 len(message) > preview_length))

    Logging.info(f"threaded?: {threaded}")
    if threaded:
        # Cut the preview message down to max length
        thread_preview = message[:preview_length]
        thread_preview += '...' if len(message) > len(thread_preview) else ''
        messages_to_channel.append(thread_preview)
        # Body begins after the end of preview, add ellipsis if the body is not empty
        body = message[preview_length:]
        body = f"...{body}" if len(body) > 0 else body
    else:
        body = message

    # Paginate the body and add page numbers
    pages = paginate(body, max_chars=page_size)
    n = len(pages)
    if n > 1:
        for i, page in enumerate(pages[:-1]):
            pages[i] = f"## **{i + 1} of {n}**\n>>> {page}"
        pages[-1] = f"## **{n} of {n}**\n>>> {pages[-1]}"

    if threaded:
        pages.append("__end initial report__")
        messages_to_thread.extend(pages)
    else:
        messages_to_channel.extend(pages)

    last_sent = None
    thread_opened = False
    try:
        for msg in messages_to_channel:
            last_sent = await target_channel.send(msg, allowed_mentions=AllowedMentions.none())

        if threaded:
            if last_sent is None:
                Logging.error(f"Message requiring thread was not sent: {message}")
                return None, False
            target_channel = await open_thread(last_sent, author_name, subject, message)
            thread_opened = True

        for msg in messages_to_thread:
            last_sent = await target_channel.send(msg, allowed_mentions=AllowedMentions.none())
        return last_sent, thread_opened
    except HTTPException as e:
        Logging.error(e, exc_info=True)
        await ir(interaction).send_message('Oops! Something went wrong.', ephemeral=True)
        return last_sent, thread_opened

async def send_receipt(
        interaction: Interaction,
        dropped_message: Message,
        target_row: DropboxTarget,
        subject: str,
        message: str,
        delivery_success: bool,
        thread_opened: bool):
    """Send a receipt to ephemeral"""
    if subject:
        message = f"# {subject}\n{message}"
    if len(message) == 0:
        # if no text, then send a response that there wasn't any text content
        await interaction.followup.send(
            content=Lang.get_locale_string('dropbox/msg_blank', interaction),
            ephemeral=True)
        return

    lines_quoted = [f"> {line}" for line in message.splitlines(keepends=True)]
    message = "".join(lines_quoted)

    # get language for status, receipt, followup
    status_msg = Lang.get_locale_string(
        'dropbox/msg_delivered' if delivery_success else 'dropbox/msg_not_delivered', interaction, author="")
    receipt_msg_header = Lang.get_locale_string('dropbox/msg_receipt_ephemeral', interaction)
    msg_followup_instructions = Lang.get_locale_string('dropbox/msg_followup_instructions', interaction)

    # Pagination in case the message length is over 2k
    pages = Utils.paginate(f"{status_msg} {receipt_msg_header}\n{message}\n\n{msg_followup_instructions}")
    page_count = len(pages)

    # send the page(s) to ephemeral response.
    for i, page in enumerate(pages[:-1]):
        if page_count > 1:
            if i > 0 and not page.startswith(">"):
                page = f"> {page}"
            page = f"## **{i + 1} of {page_count}**\n{page}"

        Logging.debug(f"page {i + 1} length: {len(page)}")
        Logging.debug(f"sending receipt page {i + 1} of {page_count}")
        await interaction.followup.send(page, ephemeral=True)

    last_page = pages[-1]
    if page_count > 1:
        if not last_page.startswith(">"):
            last_page = f"> {last_page}"
        last_page = f"## **{page_count} of {page_count}**\n{last_page}"

    def get_confirm_view():
        return ConfirmView(
            interaction.user,
            confirm_label="Send More",
            cancel_label="All Done",
            confirmed_label="DM Sent!",
            canceled_label="Report Complete",
            timeout=confirm_view_timeout)

    # Modal confirming DM request
    confirm_view = get_confirm_view()

    Logging.debug(f"receipt last page {page_count} length: {len(last_page)}")
    Logging.debug(f"sending last receipt page {page_count} of {page_count}")
    confirm_message = await interaction.followup.send(last_page, ephemeral=True, view=confirm_view)

    await confirm_view.wait()

    if confirm_view.value is None:
        unlock_user(interaction.user.id)
        # timed out. edit message
        edited_content = confirm_message.content.replace(
            f"{msg_followup_instructions}",
            "This interaction has expired. If you'd like to send more information or attachments, start again!")
        try:
            await confirm_message.edit(content=edited_content, view=None)
        except NotFound as e:
            Logging.error(f"dropbox confirm modal failed to edit {e}", exc_info=True)
        return
    else:
        edited_content = confirm_message.content.replace(f"{msg_followup_instructions}", "")
        if confirm_view.value:
            target_channel = dropped_message.channel
            Logging.debug(f"target channel: {target_channel.id} - {target_channel.name}")

            if target_row.thread_mode == DropboxThreadMode.auto and not thread_opened:
                target_channel = await open_thread(
                    dropped_message,
                    author_info(interaction.user, False),
                    subject,
                    message)

            data = DropboxFollowup(
                interaction=interaction,
                target_channel=target_channel,
                created_at=datetime.now(timezone.utc))
            registered = await UserActionRegister.register_user_action(
                interaction,
                "DropBox",
                "listen_for_followup",
                data,
                interaction.user,
                datetime.now(timezone.utc),
                followup_timeout_seconds,
                followup_forwarding_done,
                followup_forwarding_interrupt,
                followup_forwarding_expire,
                followup_finally)

            if not registered:
                edited_content = "Ok, I won't start a new report"
            else:
                dm_result = None
                ask_again = True
                while ask_again is True and dm_result is None:
                    # Try to DM, send instructions and confirmation if DM closed
                    dm_result = await followup_dm(interaction, target_channel)
                    if dm_result is None:
                        # DM is closed
                        edited_content += Lang.get_locale_string('dropbox/dm_unable', interaction)
                        confirm_view = get_confirm_view()
                        await asyncio.sleep(1)
                        try:
                            await confirm_message.edit(content=edited_content, view=confirm_view)
                            await confirm_view.wait()
                        except NotFound as e:
                            Logging.error(f"dropbox confirm modal failed to edit {e}", exc_info=True)
                            return
                        Logging.debug(f"dropbox dm attempt. second try modal response: {confirm_view.value}")
                        ask_again = confirm_view.value
                if confirm_view.value is None:
                    edited_content += f"\n\n{get_chat_emoji('SNAIL')} You took took long, so I give up"
                else:
                    # add dm channel to listening_for_followup channels
                    Logging.debug(f"should now listen for messages from {interaction.user.id} and forward them to [[{target_channel}]]")
                    edited_content += (f"{get_chat_emoji('WARNING')} "
                                       f"I sent you a DM asking for more: {dm_result.jump_url}")
        else:
            # user declined followup
            unlock_user(interaction.user.id)
        await asyncio.sleep(0.1)
        await confirm_message.edit(content=edited_content, view=None)

async def followup_dm(interaction: Interaction, target_channel: Messageable) -> Optional[Message]:
    try:
        view = discord.ui.View()
        view.add_item(StopUserActionButton(interaction.user))
        dm_message = await interaction.user.send(
            f"## __Additional information__\n"
            f"Send messages and/or attachments and I will forward them with "
            f"the information you already provided in {interaction.channel.mention}. "
            f"I'll stop forwarding after **{Utils.to_pretty_time(followup_timeout_seconds)}**. "
            f"You can also stop me from forwarding at any time by pressing the `done` button",
            view=view)
        await target_channel.send(
            f"__**Followup started** - Forwarding DMs from {interaction.user.mention}__:",
            allowed_mentions=discord.AllowedMentions.none())
        return dm_message
    except HTTPException:
        # DM is closed
        return None

async def handle_followup(message: Message, followup: DropboxFollowup):
    """Collect followup DMs to thread"""
    if followup.last_message is not None:
        await followup.last_message.delete()
    attachments = []
    try:
        for attachment in message.attachments:
            for i in range(5):
                try:
                    this_file = discord.File(io.BytesIO(await attachment.read()), attachment.filename)
                    attachments.append(this_file)
                    break
                except NotFound as e:
                    Logging.info(f"Attachment {attachment.filename} not found {i + 1} time(s)")
                    pass
    except Exception as e:
        Logging.info(f"drop fail {e}", exc_info=True)
        ctx = Utils.BOT.get_context(message)
        await followup.target_channel.send(
            Lang.get_locale_string('dropbox/attachment_fail', ctx, author=message.author.mention))

    #  forward message from dm channel into thread
    try:
        content = message.content + f"\n-# [{message.author.name}]({message.author.id})"
        await followup.target_channel.send(content=content, files=attachments)

        view = discord.ui.View(timeout=None)
        view.add_item(StopUserActionButton(message.author))
        followup.last_message = await message.channel.send(
            "Sent. Send more messages or press this button if you're done:",
            view=view)
    except HTTPException as e:
        Logging.error(f"dropbox dm forward failed: {e}", exc_info=True)
        await message.channel.send(
            "I had a problem delivering that last message. "
            "If you see this repeatedly, you may want to try starting over later")


async def send_receipt_old(
        ctx: Union[Context, Interaction],
        user: User,
        pages: list[str],
        embed: Embed,
        attachment_names: set[str],
        drop_message: Message,
        delivery_success: bool):
    """Send a receipt: to DMs for old dropbox, to ephemeral for new dropbox"""
    if isinstance(ctx, Context):
        if user.dm_channel is None:
            await user.create_dm()
        sendable = user.dm_channel
    else:
        sendable = ctx.followup

    # get the locale versions of the messages for status, receipt header, and attachments ready to be sent
    status_msg = Lang.get_locale_string(
        'dropbox/msg_delivered' if delivery_success else 'dropbox/msg_not_delivered', ctx, author="")
    receipt_msg_header = Lang.get_locale_string('dropbox/msg_receipt', ctx, channel=ctx.channel.mention)
    if len(attachment_names) == 0:
        attachment_msg = ""
    else:
        attachment_msg_key = 'dropbox/receipt_attachment_plural' if len(
            attachment_names) > 1 else 'dropbox/receipt_attachment_singular'
        attachment_msg = Lang.get_locale_string(
            attachment_msg_key,
            ctx,
            number=len(attachment_names),
            attachments=", ".join(attachment_names)
        )
    # might as well try to stuff in as few pages as possible
    dm_header_pages = Utils.paginate(f"{status_msg}\n{receipt_msg_header}\n{attachment_msg}")


    for page in dm_header_pages:
        await sendable.send(page)

    if len(pages) == 0:
        # no text content
        if len(attachment_names) < 1:
            # if no text and no attachments, then send a response that there wasn't any text content
            await sendable.send(content=Lang.get_locale_string('dropbox/msg_blank', ctx))
    else:
        page_count = len(pages)
        # send the page(s) in code blocks to dm.
        for i, page in enumerate(pages[:-1]):
            if len(pages) > 1:
                page = f"**{i + 1} of {page_count}**\n```{page}```"
            await sendable.send(page)

        last_page = f'```{pages[-1]}```' if page_count == 1 else f"**{page_count} of {page_count}**\n```{pages[-1]}```"
        await sendable.send(last_page)
    if delivery_success and drop_message is not None:
        embed.add_field(name="receipt status", value="sent")
        # this is used if drop first before dms to add status to embed
        edited_message = await drop_message.edit(embed=embed)


####################
# The Cog
####################

class DropBox(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.dropboxes: Dict[int, Dict[int, DropboxChannel]] = {}
        self.droptargets: Dict[int, Dict[int, list[DropboxTarget]]] = {}
        self.responses = {}
        self.drop_messages: Dict[int, Dict[int, Dict[int, Message]]] = {}
        self.delivery_in_progress: Dict[int, Dict[int, Set]] = {}
        self.delete_in_progress = {}
        self.send_tasks = []
        self.clean_in_progress = False

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")

        self.bot.add_dynamic_items(DropboxButton)

        for guild in self.bot.guilds:
            await self.init_guild(guild.id)

        # TODO: replace with asyncio queue?
        if not self.deliver_to_channel.is_running():
            self.deliver_to_channel.start()
        if not self.clean_channels.is_running():
            self.clean_channels.start()

    async def init_guild(self, guild_id):
        self.dropboxes[guild_id] = {}
        self.droptargets[guild_id] = {}
        self.drop_messages[guild_id] = {}
        self.delivery_in_progress[guild_id] = {}
        self.delete_in_progress[guild_id] = {}
        # fetch dropbox channels per server
        for row in await DropboxChannel.filter(serverid=guild_id):
            self.dropboxes[guild_id][row.sourcechannelid] = row

        guild_row = await self.bot.get_guild_db_config(guild_id)
        for view in await guild_row.dropbox_views:
            for target in await view.targets:
                if view.channelid not in self.droptargets[guild_id]:
                    self.droptargets[guild_id][view.channelid] = []
                self.droptargets[guild_id][view.channelid].append(target)

    async def cog_unload(self):
        Logging.info(f"\t{self.qualified_name}::cog_unload")
        await asyncio.gather(*self.send_tasks)
        self.deliver_to_channel.cancel()
        self.clean_channels.cancel()

    async def cog_check(self, ctx):
        return ((ctx.guild is None and ctx.command.name == "done") or
                (ctx.guild is not None and
                 (ctx.author.guild_permissions.ban_members
                  or await Utils.permission_manage_bot(ctx))))

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.dropboxes[guild.id]
        del self.droptargets[guild.id]
        del self.drop_messages[guild.id]
        del self.delivery_in_progress[guild.id]
        del self.delete_in_progress[guild.id]
        await DropboxChannel.filter(serverid=guild.id).delete()

    @tasks.loop(seconds=1.0)
    async def unlock_sweep(self):
        """Clean up expired user locks"""
        now = datetime.now(timezone.utc)
        for user_id, start_time in dict(user_locks).items():
            expires_at = start_time + timedelta(seconds=user_lock_seconds)
            if now > expires_at:
                del user_locks[user_id]

    # TODO: replace with asyncio queue?
    @tasks.loop(seconds=0.5)
    async def deliver_to_channel(self):
        send_tasks = []
        try:
            for guild_id, guild_queue in self.drop_messages.items():
                for channel_id, message_queue in guild_queue.items():
                    # get dropbox channel
                    drop_channel = self.bot.get_channel(self.dropboxes[guild_id][channel_id].targetchannelid)
                    working_queue = dict(message_queue)
                    for message_id, message in working_queue.items():
                        if channel_id not in self.delivery_in_progress[guild_id]:
                            self.delivery_in_progress[guild_id][channel_id] = set()
                        if message_id not in self.delivery_in_progress[guild_id][channel_id]:
                            self.delivery_in_progress[guild_id][channel_id].add(message_id)
                            send_tasks.append(self.bot.loop.create_task(self.drop_message_impl(message, drop_channel)))
                            # await self.drop_message_impl(message, drop_channel)
                            # await asyncio.gather(*send_tasks)
                            return
            await asyncio.gather(*send_tasks)
        except CancelledError as e:
            raise e
        except Exception as e:
            await Utils.handle_exception("Dropbox gather send tasks failed", e)

    async def drop_message_impl(self, source_message: Message, drop_channel: TextChannel):
        """
        handles copying to dropbox, sending confirm message in channel, sending dm receipt, and deleting original
        for each message in any dropbox
        """
        guild_id = source_message.channel.guild.id
        source_channel_id = source_message.channel.id
        source_message_id = source_message.id
        attachments = []
        attachment_names = set()
        my_dropped_message = None
        pages = Utils.paginate(source_message.content)
        page_count = len(pages)
        embed = prepare_author_embed(source_message.author)

        # TODO: add retry logic

        # get the db row for this dropbox.
        if source_channel_id in self.dropboxes[guild_id]:
            drop = self.dropboxes[guild_id][source_channel_id]
        else:
            # should only return one entry because of how rows are added
            try:
                drop = await DropboxChannel.get(serveri=guild_id, sourcechannelid=source_channel_id)
            except DoesNotExist:
                Logging.error(f"no dropbox found for channel {source_channel_id}")
                await Logging.bot_log(f"no dropbox found for channel {source_channel_id}")
                return

        ctx = await self.bot.get_context(source_message)

        try:
            # send embed and message to the dropbox channel
            try:
                for attachment in source_message.attachments:
                    """try to download attachments."""
                    for i in range(5):
                        try:
                            this_file = discord.File(io.BytesIO(await attachment.read()), attachment.filename)
                            attachments.append(this_file)
                            attachment_names.add(attachment.filename)
                            break
                        except NotFound as e:
                            Logging.info(f"Attachment {attachment.filename} not found {i+1} time(s)")
                            pass
            except Exception as e:
                Logging.info(f"drop fail {e}", exc_info=True)
                await drop_channel.send(
                    Lang.get_locale_string('dropbox/attachment_fail', ctx, author=source_message.author.mention))
            
            if len(pages) == 0:
                # means no text content included
                if len(attachment_names) < 1:
                    # if there aren't any attachments, include a message indicating that
                    my_dropped_message = await drop_channel.send(
                        embed=embed, content=Lang.get_locale_string('dropbox/msg_blank', ctx))
                else:
                    my_dropped_message = await drop_channel.send(embed=embed, files=attachments)
            else:
                # deliver all the pages of text content
                for i, page in enumerate(pages[:-1]):
                    if len(pages) > 1:
                        page = f"**{i+1} of {page_count}**\n{page}"
                    await drop_channel.send(page)
                last_page = pages[-1] if page_count == 1 else f"**{page_count} of {page_count}**\n{pages[-1]}"
                my_dropped_message = await drop_channel.send(embed=embed, content=last_page, files=attachments)
            
            # TODO: try/ignore: add reaction for "claim" "flag" "followup" "delete"
            msg = Lang.get_locale_string('dropbox/msg_delivered', ctx, author=source_message.author.mention)
            delay = drop.deletedelayms / 1000
            if delay:
                await ctx.send(msg, delete_after=delay)
            else:
                await ctx.send(msg)
            delivery_success = True
        except Exception as e:
            delivery_success = False
            msg = Lang.get_locale_string('dropbox/msg_not_delivered', ctx, author=source_message.author.mention)
            await ctx.send(msg)
            await Utils.guild_log(guild_id, "broken dropbox...? Call alex, I guess")
            await Utils.handle_exception("dropbox delivery failure", e)

        try:
            # delete original message, the confirmation of sending is deleted in clean_channels loop
            await source_message.delete()
            del self.drop_messages[guild_id][source_channel_id][source_message_id]
            self.delivery_in_progress[guild_id][source_channel_id].remove(source_message_id)
        except discord.errors.NotFound as e:
            Logging.info(f"message already deleted? {e}", exc_info=True)
            # ignore missing message
        except Exception as e:
            Logging.info(f"dropbox delete fail {e}", exc_info=True)
            pass

        # give senders a moment before spam pinging them the copy
        await asyncio.sleep(1)

        try:
            # try sending dm receipts and report in dropbox channel if it was sent or not
            if drop and drop.sendreceipt:
                await send_receipt_old(
                    ctx,
                    source_message.author,
                    pages,
                    embed,
                    attachment_names,
                    my_dropped_message,
                    delivery_success)
        except Exception as e:
            Logging.info(f"Dropbox DM receipt failed, not an issue so ignoring exception and giving up. {e}")
            if drop.sendreceipt and delivery_success:
                embed.add_field(name="receipt status", value="failed")
                # this is used if drop first before dms to add status to embed
                if my_dropped_message is not None:
                    edited_message = await my_dropped_message.edit(embed=embed)

    @tasks.loop(seconds=3.0)
    async def clean_channels(self):
        if self.clean_in_progress:
            return

        self.clean_in_progress = True

        for guild in self.bot.guilds:
            for channel_id, drop in dict(self.dropboxes[guild.id]).items():
                if drop.deletedelayms == 0:
                    # do not clear from dropbox channels with no delay set.
                    continue

                # Look for channel history. Try 10 times to fetch channel history
                # this API call fails on startup because connection is not made yet.
                now = datetime.now(timezone.utc)
                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    continue
                if channel_id not in self.delete_in_progress[guild.id]:
                    self.delete_in_progress[guild.id][channel_id] = set()

                try:
                    clean_tasks = []
                    async for message in channel.history(limit=20):
                        # check if message is queued for delivery
                        if ((channel_id in self.drop_messages[guild.id]) and
                                (message.id in self.drop_messages[guild.id][channel_id])):
                            # don't delete messages that are queued
                            continue
                        my_member = guild.get_member(message.author.id)
                        if my_member is None:
                            continue
                        is_mod = my_member.guild_permissions.ban_members or await self.bot.member_is_admin(my_member.id)
                        age = (now-message.created_at).seconds
                        expired = age > drop.deletedelayms / 1000

                        try:
                            queued_for_delete = message.id in self.delete_in_progress[guild.id][channel_id]
                        except KeyError:
                            # bot is restarting - stop processing and pick this up next time
                            break

                        # periodically clear out expired messages sent by bot and non-mod
                        if expired and not queued_for_delete and (message.author.bot or not is_mod):
                            self.delete_in_progress[guild.id][channel_id].add(message.id)
                            self.bot.loop.create_task(self.clean_message(message))
                        else:
                            pass
                    if clean_tasks:
                        await asyncio.gather(*clean_tasks)
                except (CancelledError,
                        asyncio.TimeoutError,
                        discord.DiscordServerError,
                        NotFound,
                        RuntimeError):
                    # I think these are safe to ignore...
                    pass
                except AttributeError as e:
                    # likely that channel is None because of client reconnect or other session-related transient issue
                    # this doesn't seem to persist, and is rare outside test server, so log and continue.
                    Logging.info(f"Dropbox clean AttributeError: ")
                    pass
                except aiohttp.ClientOSError:
                    await Utils.guild_log(guild.id, f"Dropbox client error. Probably safe to ignore, but check "
                                                       f"your dropbox channels to make sure they are clean.")
                    continue
                except RuntimeError:
                    await Utils.guild_log(guild.id, f"Dropbox error for guild `{guild.name}`. What's broken?")
                    # fall through and report
                except Exception as e:
                    # ignore but log
                    await Utils.handle_exception('dropbox clean failure', e)
                    continue
        await asyncio.gather(*self.send_tasks)
        self.clean_in_progress = False

    async def clean_message(self, message):
        try:
            await message.delete()
            self.delete_in_progress[message.channel.guild.id][message.channel.id].remove(message.id)
        except NotFound:
            # ignore if already deleted
            pass
        except HTTPException as e:
            await Utils.handle_exception('dropbox clean_message failure', e)

    #########################
    # App commands
    #########################

    dropbox_command = Group(
        name='dropbox',
        description='Dropbox configuration',
        guild_only=True,
        default_permissions=Permissions(manage_channels=True))

    @dropbox_command.command()
    async def prepare_channel(self, interaction: Interaction, message: str = None):
        """
        Create a dropbox member interaction message. This must be run in a
        channel that already has drop-targets configured.

        Parameters
        ----------
        interaction
        message
            Optional message. If provided, the message will appear above the dropbox button(s)

        Returns
        -------
        None
        """
        if interaction.channel.id not in self.droptargets[interaction.guild.id]:
            await ir(interaction).send_message(f"This channel has no configured dropboxes.", ephemeral=True)
            return

        channel_targets = list(self.droptargets[interaction.guild.id][interaction.channel.id])
        if not channel_targets:
            await ir(interaction).send_message(f"This channel has no configured dropboxes.", ephemeral=True)

        view = discord.ui.View(timeout=None)
        for target in channel_targets:
            view.add_item(DropboxButton(target))

        await interaction.channel.send(message, view=view)
        await ir(interaction).send_message("done!", ephemeral=True)

    @dropbox_command.command()
    @app_commands.guild_only()
    async def settings(self, interaction: Interaction, channel: Optional[TextChannel]) -> None:
        """
        Show interaction-based dropbox views and targets. This does not show old-style dropboxes; for that use `?dropbox`
        Parameters
        ----------
        interaction
        channel
            The listen channel

        Returns
        -------
        None
        """
        await ir(interaction).defer()
        guild_row = await self.bot.get_guild_db_config(interaction.guild.id)
        views = await guild_row.dropbox_views
        something_sent = False
        for view in views:
            if channel is None or channel.id == view.channelid:
                embed = Embed(title="Dropbox Settings", color=discord.Color.green())
                listen_channel = self.bot.get_channel(view.channelid)
                embed.add_field(name="Listen Channel", value=listen_channel.mention, inline=False)
                view_targets = await view.targets
                for target in view_targets:
                    embed.add_field(name="Target Channel", value=str(target), inline=False)
                await interaction.followup.send(embed=embed)
                something_sent = True
        if not something_sent:
            msg = "No dropbox views found"
            if channel is not None:
                msg += f" for channel {channel.mention}"
            await interaction.followup.send(msg, ephemeral=True)

    @dropbox_command.command()
    @app_commands.guild_only()
    async def addview(self, interaction: Interaction, channel: TextChannel) -> None:
        """
        Add a new dropbox view.
        Parameters
        ----------
        interaction
        channel
            The channel that members will see dropbox controls in.

        Returns
        -------
        None
        """
        guild_row = await self.bot.get_guild_db_config(interaction.guild.id)
        my_view, created = await DropboxView.get_or_create(
            channelid=channel.id,
            guild=guild_row)
        if channel.id not in self.droptargets[interaction.guild.id]:
            self.droptargets[interaction.guild.id][channel.id] = []
        if created:
            await ir(interaction).send_message(
                f"ok, I created a dropbox view for {channel.mention}", ephemeral=True)
        else:
            await ir(interaction).send_message(
                f"a dropbox view already exists for {channel.mention}", ephemeral=True)

    @dropbox_command.command()
    @app_commands.guild_only()
    async def removeview(self, interaction: Interaction, channel: TextChannel) -> None:
        """
        Remove a dropbox view.
        Parameters
        ----------
        interaction
        channel
            The channel that will no longer have dropbox controls.

        Returns
        -------
        None
        """
        await ir(interaction).defer(ephemeral=True)
        my_view = await DropboxView.get_or_none(channelid=channel.id)

        if channel.id in self.droptargets[interaction.guild.id]:
            del self.droptargets[interaction.guild.id][channel.id]

        if my_view is not None:
            try:
                await my_view.delete()
                await interaction.followup.send(
                    f"ok, I removed the dropbox view from {channel.mention}", ephemeral=True)
            except OperationalError as e:
                Logging.error(f"Dropbox view deletion failure: {e}")
                raise e
        else:
            await interaction.followup.send(
                f"no dropbox view exists for {channel.mention}", ephemeral=True)

    @dropbox_command.command()
    @app_commands.guild_only()
    @app_commands.choices(
        button_style=[
            Choice(name='Primary/Normal', value=ButtonStyle.primary.value),
            Choice(name='Secondary/Disabled', value=ButtonStyle.secondary.value),
            Choice(name='Success/Green', value=ButtonStyle.success.value),
            Choice(name='Danger/Red', value=ButtonStyle.danger.value),
        ],
        thread_mode=[
            Choice(name="None", value=DropboxThreadMode.none.value),
            Choice(name="Optional", value=DropboxThreadMode.auto.value),
            Choice(name="Always", value=DropboxThreadMode.always.value),
        ])

    async def addtarget(
            self,
            interaction: Interaction,
            source_channel: TextChannel,
            destination_channel: TextChannel,
            button_label: str,
            button_emoji: str,
            button_style: Choice[int],
            modal_title: str,
            modal_label: str,
            modal_placeholder: str,
            thread_mode: int) -> None:
        await ir(interaction).defer(ephemeral=True)
        guild_row = await self.bot.get_guild_db_config(interaction.guild.id)
        # automatically create a view if one doesn't exist
        view, view_created = await DropboxView.get_or_create(channelid=source_channel.id, guild=guild_row)
        target, target_created = await DropboxTarget.get_or_create(dropboxview=view, button_label=button_label)
        replace_existing = False

        if not target_created:
            confirm_view = ConfirmView(interaction.user, timeout=confirm_view_timeout)
            await interaction.followup.send(
                f"This target already exists. should I replace these settings:\n{target}",
                view=confirm_view,
                ephemeral=True)
            await confirm_view.wait()

            if confirm_view.value is None:
                await interaction.followup.send("You didn't respond in time. Canceled", ephemeral=True)
                return
            elif confirm_view.value:
                replace_existing = True
            else:
                await interaction.followup.send("Ok, I won't change it!", ephemeral=True)
                return

        if target_created or replace_existing:
            try:
                target.channelid = destination_channel.id
                target.button_emoji = button_emoji
                target.button_style = button_style.value
                target.modal_title = modal_title
                target.modal_label = modal_label
                target.modal_placeholder = modal_placeholder
                target.thread_mode = thread_mode
                await target.save()
                if source_channel.id not in self.droptargets[interaction.guild.id]:
                    self.droptargets[interaction.guild.id][source_channel.id] = []
                self.droptargets[interaction.guild.id][source_channel.id].append(target)

            except Exception as e:
                await interaction.followup.send("Dropbox target creation failed", ephemeral=True)
                Logging.error(f"Dropbox target creation failure: {e}")
                if target_created:
                    # incomplete row. don't leave it in the db
                    await target.delete()
                return

        message = f"ok, I created a new dropbox target: {source_channel.mention}->{destination_channel.mention}"
        if target_created and not replace_existing:
            message += "\nUse the `prepare_channel` command to refresh the controls"
        await interaction.followup.send(message, ephemeral=True)

    @dropbox_command.command()
    @app_commands.guild_only()
    async def removetarget(self, interaction: Interaction, target: int) -> None:
        """
        Remove a dropbox target.

        Parameters
        ----------
        interaction
        target
            The target to remove.

        Returns
        -------
        None
        """
        await ir(interaction).defer(ephemeral=True)
        my_row = await DropboxTarget.get_or_none(id=target)
        if my_row is not None:
            await my_row.delete()
            dropboxview = await my_row.dropboxview
            Logging.info(f"dropboxview [{dropboxview}]")
            this_list = self.droptargets[interaction.guild.id][dropboxview.channelid]
            Logging.info(f"dropbox targets {this_list}")
            for i, my_target in enumerate(this_list):
                if my_target.id == target:
                    Logging.info(f"removing dropbox target {i}:{my_target}")
                    del this_list[i]
                    break
            Logging.info(f"dropbox targets remaining: {this_list}")
            Logging.info(f"dropbox targets remaining: {self.droptargets[interaction.guild.id][dropboxview.channelid]}")
            await interaction.followup.send("done!", ephemeral=True)
        else:
            await interaction.followup.send("dropbox target does not exist", ephemeral=True)

    @removetarget.autocomplete('target')
    async def target_autocomplete(
            self,
            interaction: discord.Interaction,
            current: str) -> list[app_commands.Choice[str]]:
        guild_row = await self.bot.get_guild_db_config(interaction.guild.id)
        targets = await DropboxTarget.filter(dropboxview__guild=guild_row)

        async def make_target_name(target: DropboxTarget) -> str:
            view = await target.dropboxview
            channel = self.bot.get_channel(view.channelid)
            return f"#{channel.name}: [{target.button_label}]"

        # generator for all cog names:
        all_matching_targets = [i for i in targets if current.lower() in await make_target_name(i)]
        # islice to limit to 25 options (discord API limit)
        some_targets = list(islice(all_matching_targets, 25))
        # convert matched list into list of choices
        ret = [app_commands.Choice(name=await make_target_name(c), value=c.id) for c in some_targets]
        return ret

    #########################
    # Chat commands
    #########################

    @commands.group(name="dropbox", invoke_without_command=True)
    @commands.guild_only()
    async def dropbox(self, ctx):
        """List the dropbox settings. Use sub-commands to configure dropboxes

        Parameters
        ----------
        ctx
        """
        # list dropbox channels
        embed = Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("dropbox/list", ctx, server_name=ctx.guild.name))
        for source, dropbox in self.dropboxes[ctx.guild.id].items():
            source_channel = self.bot.get_channel(source)
            target_channel = self.bot.get_channel(dropbox.targetchannelid)
            embed.add_field(name=f"From",
                            value=Utils.get_channel_description(self.bot, source_channel.id),
                            inline=True)
            embed.add_field(name=f"To",
                            value=Utils.get_channel_description(self.bot, target_channel.id),
                            inline=True)
            embed.add_field(name=f"Delete After",
                            value=Utils.to_pretty_time(dropbox.deletedelayms/1000) or "off",
                            inline=True)
            embed.add_field(name=f"send receipt",
                            value=dropbox.sendreceipt,
                            inline=True)
            embed.add_field(name="__                                             __",
                            value="__                                             __",
                            inline=False)
        if len(self.dropboxes[ctx.guild.id]) == 0:
            embed.add_field(name="Not Set", value="Add dropboxes using `dropbox add` command")
        await ctx.send(embed=embed)

    @dropbox.command()
    @commands.guild_only()
    async def add(self, ctx, source_channel: discord.TextChannel, target_channel: discord.TextChannel):
        """
        Add a dropbox channel. Messages sent by non-moderator members will
        be delivered from the source channel to a destination channel.
        Destination can be public or private, as long as the bot has access.

        Parameters
        ----------
        ctx
        source_channel
            ID of the source channel
        target_channel
            ID of the destination channel

        Returns
        -------

        """
        sourceid = source_channel.id
        targetid = target_channel.id

        # validate channel ids
        source_channel = self.bot.get_channel(sourceid)
        target_channel = self.bot.get_channel(targetid)
        if not source_channel:
            await ctx.send(
                Lang.get_locale_string(
                    'dropbox/channel_not_found', ctx, channel_id=sourceid))
        if not target_channel:
            await ctx.send(
                Lang.get_locale_string(
                    'dropbox/channel_not_found', ctx, channel_id=targetid))
        if not source_channel or not target_channel:
            # valid source and target channels are required
            return

        # initialize to None for the case of adding a new entry
        update_entry = None

        # channel descriptions
        source_description = Utils.get_channel_description(self.bot, sourceid)
        new_target_description = Utils.get_channel_description(self.bot, targetid)
        old_target_description = ""

        def update(choice):
            nonlocal update_entry
            update_entry = choice

        if sourceid in self.dropboxes[ctx.guild.id]:
            # existing source channel. ask user to confirm
            old_target_description = Utils.get_channel_description(
                self.bot,
                self.dropboxes[ctx.guild.id][sourceid].targetchannelid)
            try:
                await Questions.ask(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    Lang.get_locale_string('dropbox/override_confirmation',
                                           ctx,
                                           source=source_description,
                                           old_target=old_target_description,
                                           new_target=new_target_description),
                    [
                        Questions.Option('YES', handler=lambda: update(True)),
                        Questions.Option('NO', handler=lambda: update(False))
                    ], delete_after=True, locale=ctx)
            except asyncio.TimeoutError as e:
                update(False)

        if update_entry is False:
            # user chose not to update
            await ctx.send(Lang.get_locale_string('dropbox/not_updating', ctx))
            return

        if update_entry:
            # user chose to update
            msg = Lang.get_locale_string('dropbox/updated',
                                         ctx,
                                         source=source_description,
                                         old_target=old_target_description,
                                         new_target=new_target_description)
        else:
            # no existing source. adding a new dropbox
            msg = Lang.get_locale_string('dropbox/added',
                                         ctx,
                                         source=source_description,
                                         target=new_target_description)

        try:
            # update local mapping and save to db
            db_row, created = await DropboxChannel.get_or_create(
                serverid=ctx.guild.id,
                sourcechannelid=sourceid)
            db_row.targetchannelid = targetid
            await db_row.save()
            self.dropboxes[ctx.guild.id][sourceid] = db_row
        except Exception as e:
            await Utils.handle_exception("Failed to update dropbox channel", e)
            await ctx.send("Can't save dropox channel.")
            return

        # message success to user
        await ctx.send(msg)

    @dropbox.command()
    @commands.guild_only()
    async def remove(self, ctx, source_channel: discord.TextChannel):
        """Remove a dropbox channel. Stop delivering messages from the given channel.

        Parameters
        ----------
        ctx
        source_channel: discord.TextChannel
            ID of the source channel.

        Returns
        -------

        """
        sourceid = source_channel.id
        source_description = Utils.get_channel_description(self.bot, sourceid)
        if sourceid not in self.dropboxes[ctx.guild.id]:
            await ctx.send(Lang.get_locale_string('dropbox/not_removed', ctx, source=source_description))
            return

        try:
            drop_row = await DropboxChannel.get(serverid=ctx.guild.id,
                                                sourcechannelid=sourceid)
            await drop_row.delete()
            del self.dropboxes[ctx.guild.id][sourceid]
        except DoesNotExist:
            await ctx.send("no such channel to remove from dropboxes")
        except MultipleObjectsReturned:
            await ctx.send("too many dropbox channels match that id???")
        except Exception as e:
            await Utils.handle_exception('dropbox delete failure', e)
            raise e
        await ctx.send(Lang.get_locale_string('dropbox/removed', ctx, source=source_description))

    @dropbox.command(aliases=['delay', 'delete_delay'])
    @commands.guild_only()
    async def set_delay(self, ctx, channel: discord.TextChannel, delay: float):
        """Set the lifespan for response messages in the channel

        Also applies to any non-mod messages, so the delay time must be
        greater than the initial wait for message drops.

        Parameters
        ----------
        ctx
        channel: discord.TextChannel
            Channel mention or ID
        delay: int
            Time until responses expire (seconds)
        """
        if channel.id in self.dropboxes[ctx.guild.id]:
            drop_row = self.dropboxes[ctx.guild.id][channel.id]
            drop_row.deletedelayms = int(delay * 1000)
            await drop_row.save()
            t = Utils.to_pretty_time(delay)
            await ctx.send(
                Lang.get_locale_string(
                    'dropbox/set_delay_success',
                    ctx,
                    channel=channel.mention,
                    time=t))
        else:
            await ctx.send(
                Lang.get_locale_string(
                    'dropbox/set_delay_fail',
                    ctx,
                    channel=channel.mention))

    @dropbox.command()
    @commands.guild_only()
    async def set_receipt(self, ctx, source_channel: discord.TextChannel, receipt_setting: bool):
        """Enable/disable DM receipts. When set, a copy of each dropbox message is sent by DM to the author.

        Parameters
        ----------
        ctx
        source_channel: discord.TextChannel
            Channel mention or ID
        receipt_setting: bool
            Boolean (on or off, 0 or 1, yes or no)
        """
        if source_channel.id in self.dropboxes[ctx.guild.id]:
            drop_row = self.dropboxes[ctx.guild.id][source_channel.id]
            drop_row.sendreceipt = receipt_setting
            await drop_row.save()
            msg = Lang.get_locale_string('dropbox/receipt_set_false', ctx, channel=source_channel.mention)
            if receipt_setting:
                msg = Lang.get_locale_string('dropbox/receipt_set_true', ctx, channel=source_channel.mention)
            await ctx.send(msg)

    #########################
    # Listeners
    #########################

    @commands.Cog.listener()
    async def on_message(self, message: discord.message):
        try:
            has_channel = hasattr(message, 'channel')
            has_guild = (has_channel and hasattr(message.channel, 'guild') and
                         message.channel.guild is not None)
            guild_has_id = (has_guild and hasattr(message.channel.guild, 'id') and
                            message.channel.guild.id is not None)
            guild_id = message.channel.guild.id if guild_has_id else None
            channel_not_in_dropboxes = (guild_id not in self.dropboxes or
                                        message.channel.id not in self.dropboxes[guild_id])
            author_not_in_guild = not hasattr(message.author, "guild") or message.author.guild is None
            is_mod = (guild_id is not None and message.author.guild_permissions.ban_members
                      or await self.bot.member_is_admin(message.author.id))
            should_followup = is_user_registered(
                message.author,
                self.qualified_name,
                DropboxFollowup.action_register_name)

            if (not message.author.bot and not has_guild and
                    should_followup and not message.content.startswith(get_prefix())):
                Logging.debug(f"got a message from {message.author}: {message.content}")
                await handle_followup(message, get_user_action(message.author).data)
        except Exception as e:
            Logging.error(e, exc_info=True)
            return

        if (message.author.bot or not has_guild or author_not_in_guild or
                channel_not_in_dropboxes or is_mod):
            # check for dropbox matching channel id
            # ignore bots and mods/admins
            return

        # queue this message id for delivery/deletion
        if message.channel.id not in self.drop_messages[guild_id]:
            self.drop_messages[guild_id][message.channel.id] = {}
        self.drop_messages[guild_id][message.channel.id][message.id] = message


async def setup(bot):
    await bot.add_cog(DropBox(bot))
