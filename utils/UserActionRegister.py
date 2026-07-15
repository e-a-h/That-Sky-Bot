from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Callable, Any, Awaitable, Optional

import discord
from discord import User, ButtonStyle, Interaction
from discord.ui import DynamicItem, Button

from utils import Logging
from utils.Emoji import get_chat_emoji
from utils.Logging import TCol
from utils.Utils import interaction_response as ir, get_member_log_name


@dataclass
class UserActionItem:
    user: User
    cog_name: str
    method_name: str
    data: Any
    expires_at: datetime
    created_at: datetime = datetime.now(timezone.utc)
    cancel_callback: Optional[Callable[[Interaction, "UserActionItem"], Awaitable[None]]] = None
    interrupt_callback: Optional[Callable[[Interaction, "UserActionItem"], Awaitable[bool]]] = None
    expiry_callback: Optional[Callable[["UserActionItem"], Awaitable[None]]] = None
    finally_callback: Optional[Callable[[Optional[Interaction], "UserActionItem"], Awaitable[None]]] = None


# shared register for DM-actions. The index is user_id,
# each user may have only one action of any type at a time
user_action_register: dict[int, UserActionItem] = {}


async def check_expiration():
    """
    Manage the lifecycle of user actions: check the expiration status of items
    in the `user_action_register` dictionary and trigger appropriate callbacks
    if conditions are met.

    The function performs the following tasks:
    1. Iterates over the items in the `user_action_register` dictionary.
    2. Compares the current time with the `expires_at` time of each item.
    3. Executes the `expiry_callback` if the item has expired and the callback is defined.
    4. Executes the `finally_callback` regardless of the expiration status, if defined.
    5. Removes expired items from the registry.
    6. Logs expiration status and remaining time of each item.

    Notes
    -----
    - Time comparison is based on UTC timezone.
    - Asynchronous callbacks are triggered to handle expiry and final actions for expired items.

    Returns
    -------
    None
        This function does not return a value; it operates on the global state of the
        `user_action_register` and interacts with associated callbacks.
    """
    now = datetime.now(timezone.utc)
    for i, item in dict(user_action_register).items():
        if item.expires_at < now:
            if item.expiry_callback is not None:
                Logging.debug(f"UserAction EXPIRES: {i}")
                await item.expiry_callback(item)
            if item.finally_callback is not None:
                Logging.debug(f"UserAction FINALLY: {i}")
                await item.finally_callback(None, item)
            del user_action_register[i]
        else:
            expires_in = item.expires_at - now
            Logging.debug(f"{TCol.Header}item expiring in {expires_in.seconds} seconds:{TCol.End}\n\t{item}")


def is_user_registered(user: User, cog_name: str, method_name: str) -> bool:
    """
    Check if a user is registered any action within a specific cog and method.

    This function verifies whether the provided user is registered for a
    specific cog and method name by checking the `user_action_register`
    dictionary.

    Parameters
    ----------
    user : User
        The user object containing the identifier to check registration for.
    cog_name : str
        The name of the cog to be verified.
    method_name : str
        The name of the method to be verified.

    Returns
    -------
    bool
        True if the user is registered for the specific cog and method,
        False otherwise.
    """
    if user.id in user_action_register:
        action = user_action_register[user.id]
        if action.cog_name == cog_name and action.method_name == method_name:
            return True
    return False


async def register_user_action(
        interaction: Interaction,
        cog_name: str,
        method_name: str,
        data: Any,
        user: User,
        created_at: datetime,
        expires_in: int,
        cancel_callback: Optional[Callable[[Interaction, UserActionItem], Awaitable[None]]] = None,
        interrupt_callback: Optional[Callable[[Interaction, UserActionItem], Awaitable[bool]]] = None,
        expiry_callback: Optional[Callable[[UserActionItem], Awaitable[None]]] = None,
        finally_callback: Optional[Callable[[Optional[Interaction], UserActionItem], Awaitable[None]]] = None) -> bool:
    """
    Register a blocking user-based action
    Parameters
    ----------
    interaction: Interaction
    cog_name
        The name of the cog that initiated the action
    method_name
        The name of the method that initiated the action
    data
    user
        The user that initiated the action
    created_at
        The time the user initiated the action
    expires_in
        The number of seconds until the action expires
    cancel_callback
        The callback to call when user is cancelling (interaction required)
    interrupt_callback
        the callback to call when the action is interrupted by another user action (interaction required)
    expiry_callback
        tha callback to call when the action expires
    finally_callback
        tha callback to call at the end of a user action lifecycle

    Returns
    -------
    boolean
        True if the action was registered, false if another action is blocking
    """
    expires_at = created_at + timedelta(seconds=expires_in)
    item = get_user_action(user)
    if item and item.interrupt_callback is not None:
        # interrupt callback exists
        interrupt = await item.interrupt_callback(interaction, item)
        if interrupt:
            # user opted to interrupt the existing action
            if item.finally_callback is not None:
                Logging.debug(f"UserAction INTERRUPT/FINALLY: {get_member_log_name(user)}")
                await item.finally_callback(interaction, item)
        else:
            Logging.debug(f"UserAction is blocking. User opted no interrupt: {get_member_log_name(user)}")
            # user opted not to start a new action
            return False
    else:
        # existing action has no interrupt, allow passive cancellation
        Logging.debug(f"No UserAction blocking. Creating new for: {get_member_log_name(user)}")
    user_action_register[user.id] = UserActionItem(
        user=user,
        cog_name=cog_name,
        method_name=method_name,
        data=data,
        created_at=created_at,
        expires_at=expires_at,
        cancel_callback=cancel_callback,
        interrupt_callback=interrupt_callback,
        expiry_callback=expiry_callback,
        finally_callback=finally_callback)
    return True


def get_user_action(user: User) -> Optional[UserActionItem]:
    return user_action_register[user.id] if user.id in user_action_register else None


# generic stop button
class StopUserActionButton(
    DynamicItem[Button],
    template=r'stopaction:(?P<id>[0-9]+)'):
    def __init__(
            self,
            user: User,
            label: str = "Done",
            emoji: str = get_chat_emoji("PEA POD"),
            style: ButtonStyle = ButtonStyle.primary) -> None:
        """
        A Generic "stop" button for gating and stopping a user-based action
        Parameters
        ----------
        user
            The owner of this button.
        """
        super().__init__(
            Button(
                style=style,
                label=label,
                emoji=emoji,
                custom_id=f'stopaction:{user.id}'))
        self.user = user

    # This is called when the button is clicked and the custom_id matches the template.
    @classmethod
    async def from_custom_id(cls, interaction: Interaction, item, match: re.Match[str], /) -> 'StopUserActionButton':
        user_id = int(match['id'])
        user = interaction.client.get_user(user_id)
        if user is None:
            # Fallback to API fetch if the user isn't cached
            try:
                user = await interaction.client.fetch_user(user_id)
            except Exception as e:
                Logging.debug(f"StopUserActionButton.from_custom_id fetch_user failed for {user_id}: {e}")
                raise
        return cls(user)

    async def interaction_check(self, interaction: Interaction) -> bool:
        # TODO: defer to cog method_interaction_check ?
        return self.user.id == interaction.user.id

    async def callback(self, interaction: Interaction) -> None:
        # Disable the button
        self.item.disabled = True
        new_view = discord.ui.View()
        new_view.add_item(self)

        # Acknowledge the interaction ASAP to prevent "Unknown interaction"
        try:
            if not ir(interaction).is_done():
                await ir(interaction).defer()  # quick ACK, no UI change yet
        except Exception as e:
            Logging.debug(f"StopUserActionButton.defer failed for {self.user.id}: {e}")

        # Edit the message using the REST endpoint (not the interaction token)
        try:
            if interaction.message:
                await interaction.message.edit(view=new_view)
        except discord.NotFound:
            Logging.debug(f"StopUserActionButton: message not found for {self.user.id}; possibly deleted.")
        except Exception as e:
            Logging.error(f"StopUserActionButton: message edit failed for {self.user.id}: {e}")

        my_action = get_user_action(self.user)
        if my_action:
            # If there's a running action, invoke its cancel and finally callbacks
            try:
                if my_action.cancel_callback:
                    Logging.debug(f"StopUserActionButton press: {self.user.id}")
                    await my_action.cancel_callback(interaction, my_action)
            finally:
                if my_action.finally_callback is not None:
                    Logging.debug(f"UserAction FINALLY {self.user.id}")
                    await my_action.finally_callback(interaction, my_action)
            Logging.debug(f"removing {self.user.id} from user_action_register")
            user_action_register.pop(self.user.id, None)
        else:
            # No running action; acknowledge with a small follow-up (we already deferred)
            await interaction.followup.send(get_chat_emoji("PEA POD"))
            return
