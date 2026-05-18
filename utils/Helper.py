from typing import Optional, Union, Any

from discord import Embed, InteractionMessage, InteractionResponded, Member, ui, ButtonStyle, User
from discord.ext.commands import Context
from discord.interactions import Interaction

from utils import Logging
from utils.Utils import interaction_response


class Sender:
    def __init__(self, ctx: Union[Context, Interaction]):
        self.ctx = ctx

    async def send(
            self,
            message: str = "",
            *,
            embed: Optional[Embed] = None,
            ephemeral: bool = False,
            **kwargs):
        """Send a message"""
        ctx = self.ctx

        my_args: dict[str, Any] = {"content": message}
        if embed is not None:
            my_args["embed"] = embed

        if isinstance(ctx, Context):
            # don't send ephemeral option in a message context
            if 'ephemeral' in kwargs:
                del kwargs['ephemeral']
            await ctx.send(**my_args, **kwargs)
        elif isinstance(ctx, Interaction):
            my_args['ephemeral'] = ephemeral
            try:
                if interaction_response(ctx).is_done():
                    await ctx.followup.send(**my_args)
                else:
                    await interaction_response(ctx).send_message(**my_args, **kwargs)
            except InteractionResponded as e:
                Logging.info(f"Sender InteractionResponded error {e}")
                await ctx.followup.send(**my_args)
        else:
            Logging.info(f"Sender must be either Context or Interaction. Found {repr(self.ctx)}")
            raise TypeError("Sender must be either Context or Interaction.")


class ConfirmView(ui.View):
    def __init__(
            self,
            user: Union[User, Member],
            confirm_label: str = "Confirm",
            cancel_label: str = "Cancel",
            confirmed_label: str = "Confirmed",
            canceled_label: str = "Canceled",
            timeout: float = 90.0):
        super().__init__(timeout=timeout)
        self.value = None
        self.user = user
        self.original_message: Optional[InteractionMessage] = None

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
