import asyncio
import math
import re
from random import randint

from discord.ext import commands

from cogs.BaseCog import BaseCog
from datetime import datetime
from discord import utils
from discord.ext.commands import command, Context, UserConverter
from utils import Configuration, Utils


class Krill(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.cool_down = dict()
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        krilled = Configuration.get_persistent_var("krilled", dict())
        for user_id, expiry in krilled.items():
            user = self.bot.get_user(user_id)
            # expiry = date(expiry)
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

    async def get_cool_down(self, ctx):
        remaining = 0
        now = datetime.now().timestamp()
        if ctx.author.id in self.cool_down:
            min_time = 120
            start_time = self.cool_down[ctx.author.id]
            elapsed = now - start_time
            remaining = max(0, min_time - elapsed)
            if remaining <= 0:
                del self.cool_down[ctx.author.id]

        # clean up expired cool-downs
        for user_id, start_time in self.cool_down.items():
            if now - start_time <= 0:
                del self.cool_down[user_id]

        if remaining > 0:
            time_display = Utils.to_pretty_time(remaining)
            await ctx.send(f"Cool it, {ctx.author.mention}. Try again in {time_display}")
            return True
        else:
            # start a new cool-down timer
            self.cool_down[ctx.author.id] = now
            return False

    @command()
    @commands.guild_only()
    async def krill(self, ctx, *args):
        # channel hard-coded because...
        if ctx.channel.id == 593565781166391316:  # memes channel
            pass
        elif not ctx.author.guild_permissions.mute_members:
            return

        if re.search(r'[o0]r[e3][o0]', ''.join(args), re.IGNORECASE):
            await ctx.send('not Oreo!')
            return

        victim = ' '.join(args)
        try:
            victim_user = await UserConverter().convert(ctx, victim)
            victim_user = ctx.message.guild.get_member(victim_user.id)
            victim_name = victim_user.nick or victim_user.name
        except Exception as e:
            victim_name = victim
            if re.search(r'@', victim_name):
                await ctx.send('sorry, I won\'t @-mention anyone like that')
                return

        # clean emoji and store non-emoji text for length evaluation
        emoji_used = Utils.EMOJI_MATCHER.findall(victim_name)
        non_emoji_text = Utils.EMOJI_MATCHER.sub('', victim_name)
        if len(non_emoji_text) > 40:
            await ctx.send("too much text!")
            return
        if len(emoji_used) > 15:
            await ctx.send("too many emoji!")
            return

        # Initial validation passed. Delete command message and check or start
        await ctx.message.delete()
        if ctx.author.id not in Configuration.get_var("ADMINS", []) and await self.get_cool_down(ctx):
            return

        # remove pattern interference
        reg_clean = re.compile(r'[.\[\](){}\\+]')
        victim_name = reg_clean.sub('', victim_name)
        bad_emoji = set()
        for emoji in emoji_used:
            if utils.get(self.bot.emojis, id=int(emoji[2])) is None:
                bad_emoji.add(emoji[2])
        for bad_id in bad_emoji:
            # remove bad emoji
            this_match = re.compile(f'<(a?):([^: \n]+):{bad_id}>')
            victim_name = this_match.sub('', victim_name)

        # EMOJI hard coded because... it must be exactly these
        head = utils.get(self.bot.emojis, id=640741616080125981)
        body = utils.get(self.bot.emojis, id=640741616281452545)
        tail = utils.get(self.bot.emojis, id=640741616319070229)
        red = utils.get(self.bot.emojis, id=641445732670373916)
        ded = utils.get(self.bot.emojis, id=641445732246880282)
        star = utils.get(self.bot.emojis, id=624094243329146900)

        time_step = 1
        step = randint(5, 9)
        distance = step * 4
        spaces = " " * distance
        spacestep = ' '*step
        message = await ctx.send(f"**{spacestep}**{victim_name} {red}{spaces}{head}{body}{tail}")
        while distance > 0:
            distance = distance - step
            spaces = " " * distance
            await message.edit(content=f"**{spacestep}**{victim_name} {red}{spaces}{head}{body}{tail}")
            await asyncio.sleep(time_step)

        distance = randint(15, 25)
        step = math.ceil(distance / 3)
        count = 0
        while count < distance:
            spaces = " " * count
            count = count + step
            secaps = " " * max(1, distance - count)
            await message.edit(content=f"**{secaps}**{star}{spaces}{ded} {victim_name}{spaces}{star}{spaces}{star}")
            await asyncio.sleep(time_step)
        await message.edit(content=f"**{secaps}**{star}{spaces}{ded} {victim_name}{spaces}{star}{spaces}{star} : *summoned by {ctx.author.mention}*")
        # await message.add_reaction(star)
        # TODO: add message id to persistent vars, listen for reactions.
        #  if reaction count >= 3 remove id from persistent
        #  announce victim has been rescued


def setup(bot):
    bot.add_cog(Krill(bot))
