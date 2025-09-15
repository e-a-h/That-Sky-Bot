"""
This module defines a cog for skybot that allows users to query
the reset time for Eye of Eden, showing both the formatted reset
timestamp and the countdown.
"""
import typing
from datetime import datetime, timedelta

import pytz
from discord import app_commands, Interaction

from cogs.BaseCog import BaseCog
from utils import Lang
from utils.Utils import interaction_response


class Eden(BaseCog):
    """
    Represents a cog used for Eye of Eden reset information commands.

    This class defines a Discord bot cog that provides a command to display
    information about the reset time and countdown for the Eye of Eden. The
    class uses Discord API interactions and provides functionality to
    send appropriately formatted responses.

    Attributes
    ----------
    cool_down : dict
        A dictionary to manage cooldowns for the commands in this cog.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.cool_down = {}

    @app_commands.command(description="Show information about reset time (and countdown) for Eye of Eden")
    @app_commands.describe(public="Show the response to others? Default is to show only you you")
    async def eden_reset(self, interaction: Interaction, public: typing.Literal['Yes', 'No'] = 'No'):
        """Shows when Eye of Eden will reset next and displays countdown.

        Args:
            interaction (Interaction): The interaction object from Discord
            public (Literal['Yes', 'No'], optional): Whether to show the response publicly.
             Defaults to 'No'.
        """
        server_zone = pytz.timezone("America/Los_Angeles")

        # get a timestamp of today with the correct hour, eden reset is 7am UTC
        dt = datetime.now().astimezone(server_zone).replace(
            hour=0, minute=0, second=0, microsecond=0)
        # sunday is weekday 7
        days_to_go = (6 - dt.weekday()) or 7
        reset_time = dt + timedelta(days=days_to_go)
        pretty_countdown = f"<t:{int(reset_time.timestamp())}:R>"
        reset_timestamp_formatted = f"<t:{int(reset_time.timestamp())}:F>"
        er_response = Lang.get_locale_string(
            "eden/reset",
            interaction,
            reset=reset_timestamp_formatted,
            countdown=pretty_countdown)
        msg = f"{er_response}"
        await interaction_response(interaction).send_message(msg, ephemeral=public == "No")


async def setup(bot):
    await bot.add_cog(Eden(bot))
