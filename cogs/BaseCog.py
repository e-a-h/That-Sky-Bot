from discord.ext.commands import Cog

from sky import Skybot


class BaseCog(Cog):
    def __init__(self, bot):
        self.bot: Skybot = bot