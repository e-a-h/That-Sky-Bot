import pytz
from discord import HTTPException
from discord.ext.commands import Converter, BadArgument, UserConverter
from pytz import UnknownTimeZoneError

from utils import Utils
from utils.Constants import ID_MATCHER, SIGNED_64_BIT_INTEGER_LIMIT


class Timezone(Converter):
    async def convert(self, ctx, argument):
        try:
            return pytz.timezone(argument)
        except UnknownTimeZoneError:
            raise BadArgument("Unknown timezone")


class DiscordUser(Converter):

    def __init__(self, id_only=False) -> None:
        super().__init__()
        self.id_only = id_only

    async def convert(self, ctx, argument):
        user = None
        match = ID_MATCHER.match(argument)
        if match is not None:
            argument = match.group(1)
        try:
            user = await UserConverter().convert(ctx, argument)
        except BadArgument:
            try:
                user = await Utils.get_user(
                    await RangedInt(
                        minimum=20000000000000000,
                        maximum=SIGNED_64_BIT_INTEGER_LIMIT).convert(ctx, argument))
            except (ValueError, HTTPException):
                pass

        if user is None or (self.id_only and str(user.id) != argument):
            raise BadArgument('user_conversion_failed')
        return user


class RangedInt(Converter):

    def __init__(self, minimum=None, maximum=None) -> None:
        self.minimum = minimum
        self.maximum = maximum

    async def convert(self, ctx, argument) -> int:
        try:
            argument = int(argument)
        except ValueError:
            raise BadArgument('NaN')
        else:
            if self.minimum is not None and argument < self.minimum:
                raise BadArgument(f'number is below minimum: {self.minimum}')
            elif self.maximum is not None and argument > self.maximum:
                raise BadArgument(f'number is above maximum: {self.maximum}')
            else:
                return argument
