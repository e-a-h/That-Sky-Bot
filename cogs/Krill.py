import asyncio
import re
from datetime import datetime
from random import randint

import discord
from discord import utils
from discord.ext import commands
from discord.ext.commands import command, UserConverter, BucketType, Command

from cogs.BaseCog import BaseCog
from utils import Configuration, Utils, Lang, Emoji
from utils.Database import KrillChannel
from utils.Utils import CHANNEL_ID_MATCHER


class Krill(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.krilled = dict()
        self.channels = dict()
        self.monsters = dict()
        self.loaded = False
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        self.krilled = Configuration.get_persistent_var("krilled", dict())
        """
        for user_id, expiry in self.krilled.items():
            user = self.bot.get_user(user_id)
            # expiry = date(expiry)
            print(f"krilled: {user_id}")
            # if date gt expiry, unkrill, else schedule unkrilling
        """

        # Load channels
        for guild in self.bot.guilds:
            my_channels = set()
            for row in KrillChannel.select(KrillChannel.channelid).where(KrillChannel.serverid == guild.id):
                my_channels.add(row.channelid)
            self.channels[guild.id] = my_channels
        self.loaded = True

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.channels[guild.id] = set()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.channels[guild.id]
        for row in KrillChannel.select().where(KrillChannel.serverid == guild.id):
            row.delete_instance()

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

    def can_mod_krill(ctx):
        return ctx.author.guild_permissions.manage_channels

    def can_krill(ctx):
        # mod, empty channel list, or matching channel required
        no_channels = ctx.cog.channels[ctx.guild.id] == set()
        channel_match = ctx.channel.id in ctx.cog.channels[ctx.guild.id]
        bypass = ctx.author.guild_permissions.mute_members
        return bypass or no_channels or channel_match

    @command()
    @commands.check(can_krill)
    @commands.cooldown(1, 120, BucketType.member)
    @commands.guild_only()
    async def krill(self, ctx, *, arg=''):
        if ctx.message.author.id in self.monsters.keys():
            now = datetime.now().timestamp()
            hour = 60 * 60
            if self.monsters[ctx.author.id] + hour > now:
                remain = (self.monsters[ctx.author.id] + hour) - now
                await ctx.send(f"{ctx.author.mention} is a horrible person and can spend the next {Utils.to_pretty_time(remain)} thinking about what they've done")
                return
        o = r'[o0ØǑǒǪǫǬǭǾǿŌōŎŏŐőòóôõöÒÓÔÕÖỗởOø⌀Ơơᵒ𝕠🅞⓪ⓞⓄớồ🇴]'
        r = r'[rȐƦȑȒȓʀʁŔŕŖŗŘřℛℜℝ℞℟ʳᖇɹ𝕣🅡ⓡⓇ🇷]'
        e = r'[eế3ĒēĔĕĖėëĘęĚěȨȩɘəɚɛ⋲⋳⋴⋵⋶⋷⋸⋹⋺⋻⋼⋽⋾⋿ᵉEǝ€𝕖🅔ⓔⒺểé🇪]'
        sp = r'[\s\x00\u200b\u200c\u200d]'
        oreo_pattern = re.compile(f"{o}{sp}*{r}{sp}*{e}{sp}*{o}", re.IGNORECASE)
        if oreo_pattern.search(arg):
            self.bot.get_command("krill").reset_cooldown(ctx)
            await ctx.send(f'not Oreo! {ctx.author.mention}, you monster!!')
            self.monsters[ctx.author.id] = datetime.now().timestamp()
            return

        victim = arg
        try:
            victim_user = await UserConverter().convert(ctx, victim)
            victim_user = ctx.message.guild.get_member(victim_user.id)
            victim_name = victim_user.nick or victim_user.name
        except Exception as e:
            victim_name = victim
            if re.search(r'@', victim_name):
                self.bot.get_command("krill").reset_cooldown(ctx)
                await ctx.send(f"That's a dirty trick, {ctx.author.mention}, and I'm not falling for it")
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
        blank = utils.get(self.bot.emojis, id=647913138758483977)

        time_step = 1
        step = randint(1, 2)
        distance = step * 3
        spaces = str(blank) * distance
        spacestep = str(blank) * step
        message = await ctx.send(f"{spacestep}{victim_name} {red}{spaces}{head}{body}{tail}")
        await ctx.send(f"*summoned by {ctx.author.mention}*")
        while distance > 0:
            distance = distance - step
            spaces = str(blank) * distance
            await message.edit(content=f"{spacestep}{victim_name} {red}{spaces}{head}{body}{tail}")
            await asyncio.sleep(time_step)

        step = randint(0, 2)
        distance = step*3
        count = 0
        secaps = ""
        while count < distance:
            spaces = str(blank) * count
            count = count + step
            secaps = str(blank) * (distance - count)
            await message.edit(content=f"{secaps}{star}{spaces}{ded} {victim_name}{spaces}{star}{spaces}{star}")
            await asyncio.sleep(time_step)
        await message.edit(content=f"{secaps}{star}{spaces}{ded} {victim_name}{spaces}{star}{spaces}{star}")
        # await message.add_reaction(star)
        # TODO: add message id to persistent vars, listen for reactions.
        #  if reaction count >= 3 remove id from persistent
        #  announce victim has been rescued

    @krill.error
    async def krill_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            if ctx.message.author.guild_permissions.mute_members or ctx.channel.id not in self.channels[ctx.guild.id]:
                # Bypass cooldown for mute permission and for invocations outside allowed channels
                await ctx.reinvoke()
                return
            time_display = Utils.to_pretty_time(error.retry_after)
            await ctx.send(f"Cool it, {ctx.author.mention}. Try again in {time_display}")

    @commands.group(name="krillchannel", aliases=['krillchan'], invoke_without_command=True)
    @commands.guild_only()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def krill_channel(self, ctx: commands.Context):
        """Show a list of allowed channels"""
        # if ctx.invoked_subcommand is None:
        embed = discord.Embed(timestamp=ctx.message.created_at, color=0x663399, title=Lang.get_string("krill/list_channels", server_name=ctx.guild.name))
        if len(self.channels[ctx.guild.id]) > 0:
            value = ""
            for channel_id in self.channels[ctx.guild.id]:
                channel_name = await Utils.clean(f"<#{channel_id}>", guild=ctx.guild)
                if len(channel_name) + len(f"{channel_id}") > 1000:
                    embed.add_field(name="\u200b", value=value)
                    value = ""
                value = f"{channel_name} - id:{channel_id}\n"
            embed.add_field(name="\u200b", value=value)
            await ctx.send(embed=embed)
        else:
            await ctx.send(Lang.get_string("krill/no_channels"))

    @krill_channel.command(aliases=["new"])
    @commands.check(can_mod_krill)
    @commands.guild_only()
    async def add(self, ctx: commands.Context, channel_id: str):
        """command_add_help"""
        # TODO: use Converter for channel_id
        channel_id = int(channel_id)
        channel = f"<#{channel_id}>"
        if CHANNEL_ID_MATCHER.fullmatch(channel) is None or ctx.guild.get_channel(channel_id) is None:
            await ctx.send(f"No such channel: `{channel_id}`")
            return

        row = KrillChannel.get_or_none(serverid=ctx.guild.id, channelid=channel_id)
        channel_name = await Utils.clean(channel, guild=ctx.guild)
        if row is None:
            KrillChannel.create(serverid = ctx.guild.id, channelid=channel_id)
            self.channels[ctx.guild.id].add(channel_id)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('krill/channel_added', channel=channel_name)}")
        else:
            await ctx.send(Lang.get_string('krill/channel_found', channel=channel_name))

    @krill_channel.command(aliases=["del", "delete"])
    @commands.check(can_mod_krill)
    @commands.guild_only()
    async def remove(self, ctx:commands.Context, channel_id):
        """command_remove_help"""
        channel_id = int(channel_id)
        channel = f"<#{channel_id}>"
        channel_name = await Utils.clean(channel, guild=ctx.guild)

        if channel_id in self.channels[ctx.guild.id]:
            KrillChannel.get(serverid = ctx.guild.id, channelid=channel_id).delete_instance()
            self.channels[ctx.guild.id].remove(channel_id)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('krill/channel_removed', channel=channel_id)}")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} {Lang.get_string('krill/channel_not_found', channel=channel_id)}")


def setup(bot):
    bot.add_cog(Krill(bot))
