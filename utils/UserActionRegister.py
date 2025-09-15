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
from utils.Utils import interaction_response


@dataclass
class UserActionItem:
    user: User
    cog_name: str
    method_name: str
    data: Any
    expires_at: datetime
    created_at: datetime = datetime.now(timezone.utc)
    cancel_callback: Callable[[Interaction, UserActionItem], Awaitable[None]] = None
    interrupt_callback: Callable[[Interaction, UserActionItem], Awaitable[None]] = None
    expiry_callback: Callable[[UserActionItem], Awaitable[None]] = None
    finally_callback: Callable[[Optional[Interaction], UserActionItem], Awaitable[None]] = None


# shared register for DM-actions. Key is user_id,
# each user may have only one action of any type at a time
user_action_register: dict[int, UserActionItem] = {}


async def check_expiration():
    """check and expire and actions whose time has come"""
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
        cancel_callback: Callable[[Interaction, UserActionItem], Awaitable[None]] = None,
        interrupt_callback: Callable[[Interaction, UserActionItem], Awaitable[bool]] = None,
        expiry_callback: Callable[[UserActionItem], Awaitable[None]] = None,
        finally_callback: Callable[[Optional[Interaction], UserActionItem], Awaitable[None]] = None) -> bool:
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
        interrupt = await item.interrupt_callback(interaction, get_user_action(user))
        if interrupt:
            # user opted to interrupt existing action
            if item.finally_callback is not None:
                Logging.debug(f"UserAction INTERRUPT/FINALLY: {user.id}")
                await item.finally_callback(interaction, item)
            pass
        else:
            # user opted not to start a new action
            return False
    else:
        # existing action has no interrupt, allow passive cancellation
        pass
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


def get_user_action(user: User) -> UserActionItem:
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
        A Generic "stop" button for gating and stopping a user-based actions
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
        """setup button"""
        self.user = user

    # This is called when the button is clicked and the custom_id matches the template.
    @classmethod
    async def from_custom_id(cls, interaction: Interaction, item: Button, match: re.Match[str], /):
        user_id = int(match['id'])
        user = interaction.client.get_user(user_id)

        return cls(user)

    async def interaction_check(self, interaction: Interaction) -> bool:
        # TODO: defer to cog method_interaction_check ?
        return self.user.id == interaction.user.id

    async def callback(self, interaction: Interaction) -> None:
        self.item.disabled = True
        new_view = discord.ui.View()
        new_view.add_item(self)
        await interaction_response(interaction).edit_message(view=new_view)
        my_action = get_user_action(self.user)
        if my_action:
            if my_action.cancel_callback:
                # cancel callback exists, fire it now.
                Logging.debug(f"StopUserActionButton press: {self.user.id}")
                await my_action.cancel_callback(interaction, get_user_action(self.user) or interaction)
            if my_action.finally_callback is not None:
                Logging.debug(f"UserAction FINALLY {self.user.id}")
                await my_action.finally_callback(interaction, my_action)
        else:
            # cancel callback does not exist, allow passive cancellation
            await interaction.followup.send(get_chat_emoji("PEA POD"))
            return
        Logging.debug(f"removing {self.user.id} from user_action_register")
        del user_action_register[self.user.id]
