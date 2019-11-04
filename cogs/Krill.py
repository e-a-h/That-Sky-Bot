import asyncio
import math

from cogs.BaseCog import BaseCog
from datetime import datetime
from discord import utils
from discord.ext.commands import command, Context, UserConverter
from utils import Configuration

class Krill(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.cool_down = dict()
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        krilled = Configuration.get_persistent_var("krilled", dict())
        for user_id, expiry in krilled.items():
            user = self.bot.get_user(user_id)
            expiry = date(expiry)
            print(f"krilled: {user_id}")
            # if date gt expiry, unkrill, else schedule unkrilling

    async def trigger_krill(self, user_id):
        # TODO: read configured duration
        #  set expiry
        #  save user and expiry to persistent
        #  do krill attack
        #  schedule un-attack
        pass

    async def do_krill_attack(self, user_id):
        # TODO: apply krill role (dark gray)
        #  apply muted role
        #  deliver krill message
        #  react with flame
        #  listen to flame reaction for un-krill
        pass

    async def un_krill(self, user_id):
        # TODO: remove krill role
        #  remove mute role
        pass

    def check_cool_down(self, user):
        if user.id in self.cool_down:
            min_time = 120
            start_time = self.cool_down[user.id]
            elapsed = datetime.now().timestamp() - start_time
            remaining = max(0, min_time - elapsed)
            if remaining <= 0:
                del self.cool_down[user.id]
                return 0
            else:
                return remaining
        return 0

    @command()
    async def krill(self, ctx, victim):
        if not ctx.author.guild_permissions.mute_members:
            return

        await ctx.message.delete()
        if ctx.author.id not in Configuration.get_var("ADMINS", []):
            cool_down = self.check_cool_down(ctx.author)
            if cool_down:
                # warn
                s = 's' if cool_down > 1 else ''
                await ctx.send(f"Cool it, {ctx.author.mention}. Try again in {math.ceil(cool_down)} second{s}")
                return
            else:
                # start a new cool-down timer
                self.cool_down[ctx.author.id] = datetime.now().timestamp()

        try:
            victim = await UserConverter().convert(ctx, victim)
        except Exception as e:
            await ctx.send(f"couldn't find anyone called {victim}")

        # EMOJI
        head = utils.get(self.bot.emojis, id=640741616080125981)
        body = utils.get(self.bot.emojis, id=640741616281452545)
        tail = utils.get(self.bot.emojis, id=640741616319070229)
        red = utils.get(self.bot.emojis, id=640746298856701967)
        star = utils.get(self.bot.emojis, id=624094243329146900)

        count = 28
        spaces = " " * count
        message = await ctx.send(f"{victim.mention}{red}{spaces}{head}{body}{tail}")
        step = 0.5
        while count:
            count = count-7
            spaces = " " * count
            await message.edit(content=f"{victim.mention}{red}{spaces}{head}{body}{tail}")
            await asyncio.sleep(step)
        while count < 20:
            spaces = " " * count
            count = count + 5
            await message.edit(content=f"{star}{spaces}{star}{spaces}{star}")
            await asyncio.sleep(step)


def setup(bot):
    bot.add_cog(Krill(bot))
