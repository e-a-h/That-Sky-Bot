from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Utils, Logging
from utils.Database import CogLoader


async def list_cogs(ctx):
    db_cogs = CogLoader.select()
    cog_list = []
    for row in db_cogs:
        cog_list.append(row.name)
    await ctx.send(f"These cogs are loaded: {', '.join(cog_list)}")


class CogManager(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)

    async def cog_check(self, ctx):
        if not hasattr(ctx.author, 'guild'):
            return False
        # TODO: this should probably be admin and/or custom role
        return ctx.author.guild_permissions.manage_channels

    @commands.group(name="cogloader", aliases=['cl', 'cogs'])
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def loader(self, ctx: commands.Context):
        """Show a list of cogs"""
        if ctx.invoked_subcommand is None:
            await list_cogs(ctx)

    @loader.command(aliases=["new", "create", "load"])
    @commands.guild_only()
    async def add(self, ctx: commands.Context, cog_name: str = None):
        if cog_name is None:
            await ctx.send("Try again, but with a cog name next time.")
            return

        try:
            Logging.info(f"loading cog.{cog_name}")
            # TODO: check flags
            self.bot.load_extension("cogs." + cog_name)
            CogLoader.create(name=cog_name)
            await ctx.send(f"Added {cog_name} to db")
        except Exception as e:
            await Utils.handle_exception(f"Failed to load cog {cog_name}", self, e)
            await ctx.send(f"Failed to add {cog_name}")

        await list_cogs(ctx)

    @loader.command(aliases=["delete", "del", "unload"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, cog_name: str = None):
        if cog_name is None:
            await ctx.send("Try again, but with a cog name next time.")
            return

        try:
            Logging.info(f"unloading cog.{cog_name}")
            # TODO: check flags
            self.bot.unload_extension("cogs." + cog_name)
            CogLoader.get(name=cog_name).delete_instance()
            await ctx.send(f"Removed {cog_name} from db")
        except Exception as e:
            await Utils.handle_exception(f"Failed to remove cog {cog_name}", self, e)
            await ctx.send(f"Failed to remove {cog_name}")

        await list_cogs(ctx)


def setup(bot):
    bot.add_cog(CogManager(bot))
