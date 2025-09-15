from typing import Union

from discord import Embed, InteractionResponded, ui, ButtonStyle, User
from discord.ext.commands import Context
from discord.interactions import Interaction

from utils import Logging
from utils.Utils import interaction_response


class Sender:
    def __init__(self, ctx: Union[Context, Interaction]):
        self.ctx = ctx

    async def send(self, message: str = None, *, embed: Embed = None, ephemeral: bool = None, **kwargs):
        """Send a message"""
        if isinstance(self.ctx, Context):
            if 'ephemeral' in kwargs:
                del kwargs['ephemeral']
            await self.ctx.send(message, embed=embed, **kwargs)
        elif isinstance(self.ctx, Interaction):
            try:
                if interaction_response(self.ctx).is_done():
                    await self.ctx.followup.send(message, embed=embed, ephemeral=ephemeral)
                else:
                    await interaction_response(self.ctx).send_message(message, embed=embed, ephemeral=ephemeral, **kwargs)
            except InteractionResponded as e:
                Logging.info(f"Sender InteractionResponded error {e}")
                await self.ctx.followup.send(message, embed=embed, ephemeral=ephemeral)
        else:
            Logging.info(f"Sender must be either Context or Interaction. Found {repr(self.ctx)}")
            raise TypeError("Sender must be either Context or Interaction.")


class ConfirmView(ui.View):
    def __init__(
            self,
            user: User,
            confirm_label: str = "Confirm",
            cancel_label: str = "Cancel",
            confirmed_label: str = "Confirmed",
            canceled_label: str = "Canceled",
            timeout: float = 90.0):
        super().__init__(timeout=timeout)
        self.value = None
        self.user = user
        self.original_message = None

        # Add custom buttons
        self.confirm_button = self.ConfirmViewButton(
            self,
            value=True,
            before_label=confirm_label,
            after_label=confirmed_label,
            style=ButtonStyle.green,
            emoji="\N{WHITE HEAVY CHECK MARK}")
        self.cancel_button = self.ConfirmViewButton(
            self,
            value=False,
            before_label=cancel_label,
            after_label=canceled_label,
            style=ButtonStyle.gray,
            emoji="\N{NO ENTRY SIGN}")
        self.add_item(self.confirm_button).add_item(self.cancel_button)

    # In case this is not ephemeral, only allow primary user to interact
    async def interaction_check(self, interaction: Interaction):
        return interaction.user.id == self.user.id

    class ConfirmViewButton(ui.Button):
        def __init__(self, parent, value: bool, before_label: str, after_label: str, style: ButtonStyle, emoji: str):
            self.parent = parent
            self.after_label = after_label
            self.value = value
            super().__init__(label=before_label, style=style, emoji=emoji)

        async def callback(self, interaction: Interaction):
            self.parent.value = self.value
            self.parent.stop()
            await self.parent.disable_buttons(interaction, self)

        def disable(self):
            self.disabled = True
            self.label = self.after_label

    async def on_timeout(self) -> None:
        if self.original_message is None:
            return

        edited_message = self.original_message.content + "\n\nThis interaction has expired."
        await self.original_message.edit(content=edited_message, view=None)

    async def disable_buttons(self, interaction: Interaction, button: ConfirmViewButton):
        for item in self.children:
            if isinstance(item, self.ConfirmViewButton):
                if item is button:
                    button.disable()
                else:
                    self.remove_item(item)
        await interaction_response(interaction).edit_message(view=self)
