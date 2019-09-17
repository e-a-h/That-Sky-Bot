import pytz
from discord.ext.commands import Converter, BadArgument
from pytz import UnknownTimeZoneError


class Timezone(Converter):
    async def convert(self, ctx, argument):
        try:
            return pytz.timezone(argument)
        except UnknownTimeZoneError:
            raise BadArgument("Unknown timezone")
