import importlib
import os

from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Logging, Emoji, Reloader, Utils, Configuration


class Reload(BaseCog):

    async def cog_check(self, ctx):
        return await ctx.bot.is_owner(ctx.author) or ctx.author.id in Configuration.get_var("ADMINS", [])

    @commands.command(hidden=True)
    async def reload(self, ctx, *, cog: str):
        cogs = []
        for c in ctx.bot.cogs:
            cogs.append(c.replace('Cog', ''))

        if cog in cogs:
            self.bot.unload_extension(f"cogs.{cog}")
            self.bot.load_extension(f"cogs.{cog}")
            await ctx.send(f'**{cog}** has been reloaded.')
            await Logging.bot_log(f'**{cog}** has been reloaded by {ctx.author.name}.')
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} I can't find that cog.")

    @commands.command(hidden=True)
    async def load(self, ctx, cog: str):
        if os.path.isfile(f"cogs/{cog}.py"):
            self.bot.load_extension(f"cogs.{cog}")
            if cog not in Configuration.MASTER_CONFIG["cogs"]:
                Configuration.MASTER_CONFIG["cogs"].append(cog)
                Configuration.save()
            await ctx.send(f"**{cog}** has been loaded!")
            await Logging.bot_log(f"**{cog}** has been loaded by {ctx.author.name}.")
            Logging.info(f"{cog} has been loaded")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} I can't find that cog.")

    @commands.command(hidden=True)
    async def unload(self, ctx, cog: str):
        if cog in ctx.bot.cogs:
            self.bot.unload_extension(f"cogs.{cog}")
            if cog in Configuration.MASTER_CONFIG["cogs"]:
                Configuration.get_var("cogs").remove(cog)
                Configuration.save()
            await ctx.send(f'**{cog}** has been unloaded.')
            await Logging.bot_log(f'**{cog}** has been unloaded by {ctx.author.name}')
            Logging.info(f"{cog} has been unloaded")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} I can't find that cog.")

    @commands.command(hidden=True)
    async def hotreload(self, ctx):
        message = await ctx.send("Hot reloading...")
        importlib.reload(Reloader)
        for c in Reloader.components:
            importlib.reload(c)
        Emoji.initialize(self.bot)
        Logging.info("Reloading all cogs...")
        temp = []
        for cog in self.bot.cogs:
            temp.append(cog)
        for cog in temp:
            self.bot.unload_extension(f"cogs.{cog}")
            Logging.info(f'{cog} has been unloaded.')
            self.bot.load_extension(f"cogs.{cog}")
            Logging.info(f'{cog} has been loaded.')
        await message.edit(content="Hot reload complete")


    @commands.command(hidden=True)
    async def restart(self, ctx):
        """Restarts the bot"""
        await ctx.send("Restarting...")
        await self.bot.close()


def setup(bot):
    bot.add_cog(Reload(bot))
