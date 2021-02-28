import asyncio
import re
from datetime import datetime
from random import randint, random, choice

import discord
from discord import utils
from discord.ext import commands
from discord.ext.commands import command, UserConverter, BucketType, Command

from cogs.BaseCog import BaseCog
from utils import Configuration, Utils, Lang, Emoji, Logging
from utils.Database import KrillChannel
from utils.Utils import CHANNEL_ID_MATCHER


class Krill(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.krilled = dict()
        self.channels = dict()
        self.monsters = dict()
        self.ignored = set()
        self.loaded = False
        self.oreo_filter = Configuration.get_persistent_var('oreo_filter', dict(
            o=["o", "0", "Ø", "Ǒ", "ǒ", "Ǫ", "ǫ", "Ǭ", "ǭ", "Ǿ", "ǿ", "Ō", "ō", "Ŏ",
               "ŏ", "Ő", "ő", "ò", "ó", "ô", "õ", "ö", "Ò", "Ó", "Ô", "Õ", "Ö", "ỗ",
               "ở", "O", "ø", "⌀", "Ơ", "ơ", "ᵒ", "𝕠", "🅞", "⓪", "ⓞ", "Ⓞ", "ớ",
               "ồ", "🇴", "ợ", "口", "ỡ", "ờ", "ộ", "ố", "ổ", "ọ", "ỏ", "ロ", "ㅇ",
               "°", "⭕", "о", "О", "Ο", "𝐨", "𝐎", ],
            r=["r", "Ȑ", "Ʀ", "ȑ", "Ȓ", "ȓ", "ʀ", "ʁ", "Ŕ", "ŕ", "Ŗ", "ŗ", "Ř", "ř",
               "ℛ", "ℜ", "ℝ", "℞", "℟", "ʳ", "ᖇ", "ɹ", "𝕣", "🅡", "ⓡ", "Ⓡ", "🇷",
               "厂", "尺", "𝐫", ],
            e=["e", "ế", "3", "Ē", "ē", "Ĕ", "ĕ", "Ė", "ė", "ë", "Ę", "ę", "Ě", "ě",
               "Ȩ", "ȩ", "ɘ", "ə", "ɚ", "ɛ", "⋲", "⋳", "⋴", "⋵", "⋶", "⋷", "⋸",
               "⋹", "⋺", "⋻", "⋼", "⋽", "⋾", "⋿", "ᵉ", "E", "ǝ", "€", "𝕖", "🅔",
               "ⓔ", "Ⓔ", "ể", "é", "🇪", "ề", "已", "ệ", "ê", "ễ", "ẹ", "ẽ", "è",
               "ẻ", "巨", "ㅌ", "е", "ε", "𝐞", ],
            oh=["お"],
            re=["れ"],
            sp=[r"\s", r"\x00", r"\u200b", r"\u200c", r"\u200d", r"\.", r"\[", r"\]",
                r"\(", r"\)", r"\{", r"\}", r"\\", r"\-", r"_", r"="],
            n='{0,10}'
        ))

        # TODO: this is an upgrade from old list style. remove this block after it goes into live bot.
        if 'oh' not in self.oreo_filter:
            self.oreo_filter['oh'] = ["お"]
            self.oreo_filter['re'] = ["れ"]

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
        return ctx.author.guild_permissions.mute_members

    def can_admin_krill(ctx):
        return ctx.author.guild_permissions.manage_channels

    def can_krill(ctx):
        # mod, empty channel list, or matching channel required
        no_channels = ctx.cog.channels[ctx.guild.id] == set()
        channel_match = ctx.channel.id in ctx.cog.channels[ctx.guild.id]
        bypass = ctx.author.guild_permissions.mute_members
        return bypass or no_channels or channel_match

    @commands.group(name="oreo", invoke_without_command=True)
    @commands.guild_only()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def oreo(self, ctx: commands.Context):
        """Show the oreo filter settings."""
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("krill/list_oreo_filter", ctx, server_name=ctx.guild.name))
        embed.add_field(name='Letter "o"', value=" ".join(self.oreo_filter['o']))
        embed.add_field(name='Letter "r"', value=" ".join(self.oreo_filter['r']))
        embed.add_field(name='Letter "e"', value=" ".join(self.oreo_filter['e']))
        embed.add_field(name='Letter "お"', value=" ".join(self.oreo_filter['oh']))
        embed.add_field(name='Letter "れ"', value=" ".join(self.oreo_filter['re']))
        embed.add_field(name='Inter-letter space', value=self.oreo_filter['sp'])
        embed.add_field(name='Character count', value=self.oreo_filter['n'])
        await ctx.send(embed=embed)

    @oreo.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def sniff(self, ctx: commands.Context,  *, value=''):
        """Search a string for unfiltered characters."""
        checked = ""
        found = False
        pattern = self.get_oreo_patterns()['chars']

        # TODO: recognize emojis?
        for letter in value:
            if letter not in checked:
                checked = checked + letter
            else:
                continue
            if not pattern.search(letter):
                found = True
                await ctx.send(Lang.get_locale_string("krill/letter_not_found", ctx, letter=letter))
        if not found:
            await ctx.send(Lang.get_locale_string("krill/smells_clean", ctx, value=value))

    @staticmethod
    async def validate_oreo_letter(ctx, letter):
        categories = ['o', 'r', 'e', 'oh', 're', 'お', 'れ', 'sp']
        if letter not in categories:
            await ctx.send(Lang.get_locale_string("krill/invalid_letter_category", ctx, value=', '.join(categories)))
            return False
        if letter == 'お':
            letter = 'oh'
        if letter == 'れ':
            letter = 're'
        return letter

    @oreo.command(aliases=["add", "letter"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def add_letter(self, ctx: commands.Context, letter, *, value):
        """Add a letter from the oreo filter."""
        letter = await self.validate_oreo_letter(ctx, letter)
        if not letter:
            return

        x = "space" if letter == "sp" else f"letter \"{letter}\""
        if letter != "sp":
            value = re.escape(value)
        if value in self.oreo_filter[letter]:
            await ctx.send(Lang.get_locale_string("krill/letter_already_filtered", ctx, letter=x))
            return

        self.oreo_filter[letter].append(value)
        Configuration.set_persistent_var("oreo_filter", self.oreo_filter)
        await ctx.send(Lang.get_locale_string("krill/letter_filter_added", ctx, letter=value, category=x))

    @oreo.command(aliases=["remove"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def remove_letter(self, ctx: commands.Context, letter, *, value):
        """Remove a letter from the oreo filter."""
        letter = await self.validate_oreo_letter(ctx, letter)
        if not letter:
            return

        x = "space" if letter == "sp" else f"letter \"{letter}\""
        if value not in self.oreo_filter[letter]:
            await ctx.send(Lang.get_locale_string("krill/letter_not_filtered", ctx, letter=x))
            return

        self.oreo_filter[letter].remove(value)
        Configuration.set_persistent_var("oreo_filter", self.oreo_filter)
        await ctx.send(Lang.get_locale_string("krill/letter_filter_removed", ctx, letter=value, category=x))

    @oreo.command(aliases=["reset"])
    @commands.check(can_admin_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def reset_cooldown(self, ctx: commands.Context):
        """Clear the oreo cooldown list."""
        self.monsters = dict()
        await ctx.send(Lang.get_locale_string("krill/oreo_cooldown_reset", ctx))

    @oreo.command(aliases=["list", "monsters"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def list_monsters(self, ctx: commands.Context):
        """Show a list of everyone on oreo cooldown."""
        if not self.monsters:
            await ctx.send(Lang.get_locale_string("krill/no_monsters", ctx))
            return
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("krill/list_oreo_monsters", ctx, server_name=ctx.guild.name))
        for monster in self.monsters.keys():
            bad_person = Lang.get_locale_string("krill/bad_person", ctx)
            this_member = ctx.guild.get_member(monster)
            if this_member is None:
                # remove nonexistent member
                del self.monsters[monster]
            else:
                embed.add_field(name=bad_person, value=this_member.display_name, inline=False)
        await ctx.send(embed=embed)

    @oreo.command(aliases=["monster"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def add_monster(self, ctx: commands.Context, member: discord.Member):
        """Add a member to oreo monster list."""
        await ctx.message.delete()
        self.monsters[member.id] = datetime.now().timestamp()
        await ctx.send(Lang.get_locale_string("krill/monster_added", ctx, name=member.mention))

    @oreo.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def remove_monster(self, ctx: commands.Context, member: discord.Member):
        """Remove a member from oreo monster list."""
        if member.id in self.monsters.keys():
            del self.monsters[member.id]
            await ctx.send(Lang.get_locale_string("krill/monster_removed", ctx, name=member.mention))
        else:
            await ctx.send(Lang.get_locale_string("krill/member_not_found", ctx, name=member.mention))

    @oreo.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def ignore(self, ctx: commands.Context, member: discord.Member):
        """Add a member to krill command ignore list."""
        self.ignored.add(member.id)
        await ctx.send(Lang.get_locale_string("krill/member_ignored", ctx, name=member.mention))

    @oreo.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def unignore(self, ctx: commands.Context, member: discord.Member):
        """Remove a member from krill command ignore list."""
        if member.id in self.ignored:
            self.ignored.remove(member.id)
            await ctx.send(Lang.get_locale_string("krill/member_not_ignored", ctx, name=member.mention))
        else:
            await ctx.send(Lang.get_locale_string("krill/member_not_found", ctx, name=member.mention))

    def get_oreo_patterns(self):
        # o-ø º.o r...r e é 0 º oおれ
        # ((o|0|ø|º)[ .-]*)+((r|®)[ .-]*)+((e|é)[ .-]*)+((o|0|º)[ .-]*)+
        o = f"({'|'.join(self.oreo_filter['o'])})"
        r = f"({'|'.join(self.oreo_filter['r'])})"
        e = f"({'|'.join(self.oreo_filter['e'])})"
        oo = f"({'|'.join(self.oreo_filter['oh'])})"
        rr = f"({'|'.join(self.oreo_filter['re'])})"
        sp = f"[{''.join(self.oreo_filter['sp'])}]"
        n = self.oreo_filter['n']
        oreo_pattern = re.compile(f"({o}{sp}{n})+"
                                  f"("
                                  f"({r}{sp}{n})+"
                                  f"({e}{sp}{n})+"
                                  f"|"
                                  f"({e}{sp}{n})+"
                                  f"({r}{sp}{n})+)"
                                  f"({o}{sp}{n})+",
                                  re.IGNORECASE)

        # ((お|oh)[ .-]*)+((れ|re)[ .-]*)+((お|oh)[ .-]*)+
        oreo_jp_pattern = re.compile(f"({oo}{sp}{n})+({rr}{sp}{n})+({oo}{sp}{n})+", re.IGNORECASE)

        # (o|0|º)|(r|®)|(e|é)|(o|0|º|ø)|[ .-]|(お)|(れ)
        oreo_chars = re.compile(f"{o}|{r}|{e}|{sp}|{oo}|{rr}", re.IGNORECASE)

        return dict(en=oreo_pattern, jp=oreo_jp_pattern, chars=oreo_chars)

    @command()
    @commands.check(can_krill)
    @commands.cooldown(1, 600, BucketType.member)
    @commands.guild_only()
    async def krill(self, ctx, *, arg=''):
        """Krill attack!!!"""
        if ctx.message.author.id in self.ignored:
            return

        await ctx.trigger_typing()

        if ctx.message.author.id in self.monsters.keys():
            now = datetime.now().timestamp()
            hour = 60 * 60
            penalty = 6 * hour
            if self.monsters[ctx.author.id] + penalty > now:
                remain = (self.monsters[ctx.author.id] + penalty) - now
                await ctx.send(Lang.get_locale_string("krill/oreo_cooldown_message",
                                                      ctx,
                                                      name=ctx.author.mention,
                                                      time_remaining=Utils.to_pretty_time(remain)))
                return

        patterns = self.get_oreo_patterns()
        oreo_pattern = patterns['en']
        oreo_jp_pattern = patterns['jp']
        dog_pattern = re.compile(r"\bdog\b|\bcookie\b|\bbiscuit\b|\bcanine\b", re.IGNORECASE)

        monster = False
        name_is_oreo = oreo_pattern.search(ctx.author.display_name) or oreo_jp_pattern.search(ctx.author.display_name)
        if oreo_pattern.search(arg) or oreo_jp_pattern.search(arg) or name_is_oreo or dog_pattern.search(arg):
            self.bot.get_command("krill").reset_cooldown(ctx)
            victim_name = "bad person" if name_is_oreo else ctx.author.mention
            await ctx.send(Lang.get_locale_string("krill/not_oreo", ctx, victim_name=victim_name))
            monster = True
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
                await ctx.send(Lang.get_locale_string("krill/dirty_trick", ctx, name=ctx.author.mention))
                return

        # clean emoji and store non-emoji text for length evaluation
        emoji_used = Utils.EMOJI_MATCHER.findall(victim_name)
        non_emoji_text = Utils.EMOJI_MATCHER.sub('', victim_name)
        if len(non_emoji_text) > 40:
            await ctx.send(Lang.get_locale_string("krill/too_much_text", ctx))
            await ctx.send("too much text!")
            return
        if len(emoji_used) > 15:
            await ctx.send(Lang.get_locale_string("krill/too_many_emoji", ctx))
            await ctx.send("too many emoji!")
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

        # one more backup check
        victim_is_oreo = oreo_pattern.search(victim_name) or \
                         oreo_jp_pattern.search(victim_name) or \
                         dog_pattern.search(victim_name)
        if victim_is_oreo:
            self.monsters[ctx.author.id] = datetime.now().timestamp()
            await ctx.send(Lang.get_locale_string("krill/nice_try", ctx))
            return

        # Initial validation passed. Delete command message and check or start
        Logging.info(f"krill by {Utils.get_member_log_name(ctx.author)} - args: {arg}")
        await ctx.message.delete()

        # EMOJI hard coded because... it must be exactly these
        head = utils.get(self.bot.emojis, id=640741616080125981)
        body = utils.get(self.bot.emojis, id=640741616281452545)
        tail = utils.get(self.bot.emojis, id=640741616319070229)
        red = utils.get(self.bot.emojis, id=641445732670373916)
        star = utils.get(self.bot.emojis, id=677980926378246184)
        blank = utils.get(self.bot.emojis, id=647913138758483977)
        ded = u"\U0001F916" if victim_name == "thatskybot" else utils.get(self.bot.emojis, id=641445732246880282)

        # alternate bodies
        # KrillRiderHead       664191325104504880>
        # KrillRideraTail      664191324869754881>
        # KrillRiderBodyOreo   664262338874048512>
        # KrillRiderBodya9     664239237696323596>
        # KrillRiderBodya8     664237187184853012>
        # KrillRiderBodya7     664191324911697960>
        # KrillRiderBodya6     664242877492101159>
        # KrillRiderBodya5     664235527607812107>
        # KrillRiderBodya4     664234216145289216>
        # KrillRiderBodya3     664246386727845939>
        # KrillRiderBodya2     664230982169264135>
        # KrillRiderBodya11    664259346234081283>
        # KrillRiderBodya10    664256923784314898>
        # KrillRiderBodya1     664230982378979347>
        # KrillRiderBodya      664251608212832256>

        # p.s. this will not work w/ a test bot because these emojis are on the official server
        # instead, the krill will look like "NoneNoneNone"
        chance = 0.25
        roll = random()
        if roll < chance:
            body_id = choice([
                664262338874048512,
                664239237696323596,
                664237187184853012,
                664191324911697960,
                664242877492101159,
                664235527607812107,
                664234216145289216,
                664246386727845939,
                664230982169264135,
                664259346234081283,
                664256923784314898,
                664230982378979347,
                664251608212832256
            ])
            head = utils.get(self.bot.emojis, id=664191325104504880)
            tail = utils.get(self.bot.emojis, id=664191324869754881)
            body = utils.get(self.bot.emojis, id=body_id)

        time_step = 1
        step = randint(1, 2)
        distance = step * 3
        spaces = str(blank) * distance
        spacestep = str(blank) * step
        message = await ctx.send(f"{spacestep}{victim_name} {red}{spaces}{head}{body}{tail}")
        if not monster:
            await ctx.send(Lang.get_locale_string("krill/summoned_by", ctx, name=ctx.author.mention))
        await ctx.trigger_typing()
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
            await ctx.send(Lang.get_locale_string("krill/cooldown_message",
                                                  ctx,
                                                  name=ctx.author.mention,
                                                  time_remaining=time_display))

    @commands.group(name="krillchannel", aliases=['krillchan'], invoke_without_command=True)
    @commands.guild_only()
    @commands.check(can_admin_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def krill_channel(self, ctx: commands.Context):
        """Show a list of allowed channels"""
        # if ctx.invoked_subcommand is None:
        embed = discord.Embed(timestamp=ctx.message.created_at,
                              color=0x663399,
                              title=Lang.get_locale_string("krill/list_channels", ctx, server_name=ctx.guild.name))
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
            await ctx.send(Lang.get_locale_string("krill/no_channels", ctx))

    @krill_channel.command(aliases=["new"])
    @commands.check(can_admin_krill)
    @commands.guild_only()
    async def add(self, ctx: commands.Context, channel_id: str):
        """Add a channel from list of channels in which krill command is allowed"""
        # TODO: use Converter for channel_id
        channel_id = int(channel_id)
        channel = f"<#{channel_id}>"
        if CHANNEL_ID_MATCHER.fullmatch(channel) is None or ctx.guild.get_channel(channel_id) is None:
            await ctx.send(Lang.get_locale_string("krill/no_such_channel", ctx, channel_id=channel_id))
            return

        row = KrillChannel.get_or_none(serverid=ctx.guild.id, channelid=channel_id)
        channel_name = await Utils.clean(channel, guild=ctx.guild)
        if row is None:
            KrillChannel.create(serverid = ctx.guild.id, channelid=channel_id)
            self.channels[ctx.guild.id].add(channel_id)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {Lang.get_locale_string('krill/channel_added', ctx, channel=channel_name)}")
        else:
            await ctx.send(Lang.get_locale_string('krill/channel_found', ctx, channel=channel_name))

    @krill_channel.command(aliases=["del", "delete"])
    @commands.check(can_admin_krill)
    @commands.guild_only()
    async def remove(self, ctx:commands.Context, channel_id):
        """Remove a channel from list of channels in which krill command is allowed"""
        channel_id = int(channel_id)
        channel = f"<#{channel_id}>"
        channel_name = await Utils.clean(channel, guild=ctx.guild)

        if channel_id in self.channels[ctx.guild.id]:
            KrillChannel.get(serverid = ctx.guild.id, channelid=channel_id).delete_instance()
            self.channels[ctx.guild.id].remove(channel_id)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {Lang.get_locale_string('krill/channel_removed', ctx, channel=channel_id)}")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} {Lang.get_locale_string('krill/channel_not_found', ctx, channel=channel_id)}")


def setup(bot):
    bot.add_cog(Krill(bot))
