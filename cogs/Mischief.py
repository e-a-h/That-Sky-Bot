import re
from dataclasses import dataclass
from datetime import datetime
from random import random, choice

import discord
from discord import AllowedMentions
from discord.ext import commands, tasks
from discord.ext.commands import BucketType

import utils.Utils
from cogs.BaseCog import BaseCog
from utils import Utils, Configuration, Logging


class Mischief(BaseCog):
    cooldown_time = 600.0
    name_mischief_chance = 0.0
    name_cooldown = dict()
    role_map = {

        "bean": 902462040596164619,
        "bird": 901960866226913340,
        "buff moth": 902297335743279174,
        "bunny": 903083512951869530,
        "butterfly": 901960358267326494,
        "candle": 902327931680989285,
        "cosmic manta": 901964236396314645,
        "crab": 819720424992145458,
        "dreams skater": 902648539014893680,
        "elder bird": 902307770815119370,
        "flight guide": 902369136468959242,
        "gratitude guide": 902455240404647948,
        "jellyfish": 901960274754555924,
        "just a fish": 902616235005583400,
        "koi fish": 902321584159723560,
        "krilled skykid": 902346221665005629,
        "manta": 901959573974425640,
        "moth": 902294230679048222,
        "not a krill": 818924325633654824,
        "oreo": 902295610454069378,
        "pair of pants": 902446961414770728,
        "performance guide": 965759873935609916,
        "prophecy guide": 902418537832906752,
        "rhythm guide": 902330765352783912,
        "shadow": 901960767119704064,
        "spirit": 902293337028055111,
        "thatskybot": 902434147916709928,
        "totally a krill": 818978303243190302,
        "tuna king": 827341301833531422,
        "weasel": 902311536125673503,
        "me again": 0
    }

    role_counts = {}

    def __init__(self, bot):
        super().__init__(bot)
        for guild in self.bot.guilds:
            self.init_guild(guild)
        self.periodic_task.start()
        self.name_task.start()
        self.name_cooldown_time = float(Configuration.get_persistent_var("name_mischief_cooldown", 10.0))
        self.name_mischief_chance = float(Configuration.get_persistent_var("name_mischief_chance", 0.01))
        self.mischief_names = [
          "Cackling {name}",
          "Crabby {name}!",
          "Krilled {name}",
          "Spirit {name}",
          "Eye of {name}",
          "Spooky McSpooky {name}",
          "Dark {name}",
          "Corrupted {name}",
          "Shattered {name}",
          "LOCALIZE {name}",
          "QUEST_NIGHT_{name}",
          "{name}'s broken reflection",
          "{name} spoke too soon",
          "{name} splashed with dark water",
          "{name} look behind you",
          "{name} destroyer of candles",
          "{name} [0 cosmetics]",
          "{name} hoarder of candles",
          "{name} is stormlocked",
          "shard landed on {name}",
          "{name} oobed too deep",
          "{name} fell into GW",
          "Extinguished {name}",
          "crab{name}",
          "trick or {name}",
          "the spirit of {name}",
          "{name} got mantalulled",
          "{name} is behind you",
          "a curse upon {name}",
          "{name} the terrible",
          "{name} the horrible",
          "fear the {name}",
          "{name} [0 candles]",
          "Regrettable {name}",
          "{name} scissorhands",
          "{name} saladfingers",
          "{name} of the night",
          "{name} is one candle short",
          "{name} is krill certified",
          "{name} got server split",
          "{name} crashed in Eden",
          "Honking {name}",
          "Beaned {name}",
          "{name} missed 1 Eden Statue",
          "{name} the arsonist",
          "{name} is a toilet krill",
          "{name} has treats!",
          "{name} should be feared",
          "spooky scary {name}",
          "{name} steals candy from skykids",
          "{name} is looking for spells",
          "oh no, a ghost! {name}!",
          "{name} is a treat for the krills",
          "{name} cast a spell on Skybot",
          "{name} has released the crabs",
          "{name} the crab roaster",
          "{name} became krillbait"
        ]

    def cog_unload(self):
        self.periodic_task.cancel()
        self.name_task.cancel()

    def init_guild(self, guild):
        # init guild-specific dicts and lists
        for guild in self.bot.guilds:
            self.name_cooldown[str(guild.id)] = Configuration.get_persistent_var(f"name_cooldown_{guild.id}", dict())
            # Configuration.set_persistent_var(f"name_cooldown_{guild.id}", self.name_cooldown[str(guild.id)])

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        Configuration.del_persistent_var(f"name_cooldown_{guild.id}")

    @tasks.loop(seconds=1)
    async def name_task(self):
        # periodic task to run while cog is loaded
        now = datetime.now().timestamp()
        try:
            for guild in self.bot.guilds:
                updated_name_cooldown = {}
                haunted_role = discord.utils.get(guild.roles, name="haunted")
                if haunted_role is None:
                    # server must have a haunted role or this is ignored
                    continue

                for str_uid, mischief_name_obj in dict(self.name_cooldown[str(guild.id)]).items():
                    if (now - mischief_name_obj['timestamp']) < self.name_cooldown_time:
                        updated_name_cooldown[str_uid] = mischief_name_obj
                    else:
                        # reset name to normal
                        my_member = guild.get_member(int(str_uid))
                        if not my_member:
                            continue
                        if mischief_name_obj['mischief_name'] == my_member.display_name:
                            # mischief name is still in use when mischief expires
                            # restore display name if member hasn't changed name
                            if mischief_name_obj['name_is_nick']:
                                await my_member.edit(nick=mischief_name_obj['name_normal'])
                            else:
                                await my_member.edit(nick=None)
                        if haunted_role in my_member.roles:
                            await my_member.remove_roles(haunted_role)

                self.name_cooldown[str(guild.id)] = updated_name_cooldown
                Configuration.set_persistent_var(f"name_cooldown_{guild.id}", updated_name_cooldown)
        except Exception as e:
            await utils.Utils.handle_exception("mischief name task error", self.bot, e)

    @tasks.loop(seconds=600)
    async def periodic_task(self):
        # periodic task to run while cog is loaded

        # remove expired cooldowns
        now = datetime.now().timestamp()

        try:
            cooldown = Configuration.get_persistent_var(f"mischief_cooldown", dict())
            updated_cooldown = {}
            # key for loaded dict is a string
            for str_uid, member_last_access_time in cooldown.items():
                if (now - member_last_access_time) < self.cooldown_time:
                    updated_cooldown[str_uid] = member_last_access_time
            Configuration.set_persistent_var(f"mischief_cooldown", updated_cooldown)
        except:
            Logging.info("can't clear cooldown")

        # update role count storage (because it's slow)
        try:
            guild = Utils.get_home_guild()
            for role_id in self.role_map.values():
                my_role = guild.get_role(role_id)
                if my_role is not None:
                    self.role_counts[str(role_id)] = len(my_role.members)
        except:
            Logging.info("can't update role counts")

    @commands.group(name="name_mischief", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    async def name_mischief(self, ctx):
        await ctx.send(f"""
name mischief is at {self.name_mischief_chance*100}%
name cooldown is {self.name_cooldown_time} seconds
            """)

    @name_mischief.command()
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    async def set_chance(self, ctx, chance: float):
        self.name_mischief_chance = chance/100
        Configuration.set_persistent_var("name_mischief_chance", chance/100)
        await ctx.invoke(self.name_mischief)

    @name_mischief.command()
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    async def set_cooldown(self, ctx, seconds: int):
        self.name_cooldown_time = seconds
        Configuration.set_persistent_var("name_mischief_cooldown", seconds)
        await ctx.invoke(self.name_mischief)

    @commands.cooldown(1, 60, BucketType.member)
    @commands.max_concurrency(3, wait=True)
    @commands.command()
    async def mischief(self, ctx):
        if ctx.guild and not Utils.can_mod_official(ctx):
            return

        member_counts = Configuration.get_persistent_var(f"mischief_usage", dict())
        max_member_id = max(member_counts, key=member_counts.get)
        wishes_granted = sum(member_counts.values())
        guild = Utils.get_home_guild()
        max_user: discord.Member = guild.get_member(int(max_member_id))
        await ctx.send(f"{len(member_counts)} people have gotten mischief roles.\n"
                       f"I have granted {wishes_granted} wishes.\n"
                       f"{max_user.mention} has wished the most, with {member_counts[max_member_id]} wishes granted.",
                       allowed_mentions=AllowedMentions.none())

    @commands.cooldown(1, 60, BucketType.member)
    @commands.max_concurrency(3, wait=True)
    @commands.command()
    async def team_mischief(self, ctx):
        if ctx.guild and not Utils.can_mod_official(ctx):
            return

        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0xFFBD1C,
            title="Mischief!")

        guild = Utils.get_home_guild()

        for role_name, role_id in self.role_map.items():
            this_role: discord.role = guild.get_role(role_id)

            if this_role is None:
                continue

            member_count = self.role_counts[str(role_id)]
            embed.add_field(name=this_role.name, value=str(member_count), inline=True)

            if len(embed.fields) == 25:
                await ctx.send(embed=embed, allowed_mentions=AllowedMentions.none())
                embed = discord.Embed(
                    timestamp=ctx.message.created_at,
                    color=0xFFBD1C,
                    title="mischief continued...")

        await ctx.send(embed=embed, allowed_mentions=AllowedMentions.none())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            # don't rename bots
            return

        if hasattr(message.author, "guild"):
            # guild required for nickname shenanigans
            try:
                my_member = message.guild.get_member(message.author.id)
                if str(message.guild.id) in self.name_cooldown and \
                        str(my_member.id) not in self.name_cooldown[str(message.guild.id)]:
                    roll = random()
                    if roll < self.name_mischief_chance:
                        # await message.channel.send("spooky")
                        now = datetime.now().timestamp()
                        haunted_role = discord.utils.get(message.guild.roles, name="haunted")
                        await my_member.add_roles(haunted_role)
                        nick_limit = 32
                        random_name = choice(self.mischief_names)
                        old_name = my_member.display_name
                        is_nick = my_member.nick is not None
                        diff = nick_limit - len(random_name) + 6
                        chomped_name = old_name[0:diff]
                        mischief_name = random_name.format(name=chomped_name)

                        name_obj = {
                            "mischief_name": mischief_name,
                            "timestamp": int(now),
                            "name_normal": old_name,
                            "name_is_nick": 1 if is_nick else 0
                        }

                        self.name_cooldown[str(message.guild.id)][str(my_member.id)] = name_obj
                        await my_member.edit(nick=mischief_name)
                        Configuration.set_persistent_var(
                            f"name_cooldown_{message.guild.id}",
                            self.name_cooldown[str(message.guild.id)]
                        )
            except Exception as e:
                Logging.info("mischief onmessage namer error")
                Logging.info(e)

        uid = message.author.id

        try:
            guild = Utils.get_home_guild()
            my_member: discord.Member = guild.get_member(uid)
            if my_member is None or len(message.content) > 60 or len(my_member.roles) < 2:
                return
        except:
            return

        # try to create DM channel
        try:
            channel = await my_member.create_dm()
        except:
            # Don't message member because creating DM channel failed
            channel = None

        now = datetime.now().timestamp()

        triggers = [
            "i wish i was",
            "i wish i were",
            "i wish i could be",
            "i wish to be",
            "i wish to become",
            "i wish i could become",
            "i wish i could turn into",
            "i wish to turn into",
            "i wish you could make me",
            "i wish you would make me",
            "i wish you could turn me into",
            "i wish you would turn me into",
        ]

        remove = False
        pattern = re.compile(f"(?:skybot,? *)?({'|'.join(triggers)})(?: (a|an|the))? (.*)", re.I)
        result = pattern.match(message.content)

        if result is None:
            # no match. don't remove or add roles
            return

        # get selection out of matching message
        selection = result.group(3).lower().strip()
        if selection in ["myself", "myself again", "me"]:
            selection = "me again"

        if selection not in self.role_map:
            return

        # Selection is now validated
        # Check Cooldown
        cooldown = Configuration.get_persistent_var(f"mischief_cooldown", dict())
        member_last_access_time = 0 if str(uid) not in cooldown else cooldown[str(uid)]
        cooldown_elapsed = now - member_last_access_time
        remaining = self.cooldown_time - cooldown_elapsed

        ctx = await self.bot.get_context(message)
        if not Utils.can_mod_official(ctx) and (cooldown_elapsed < self.cooldown_time):
            try:
                remaining_time = Utils.to_pretty_time(remaining)
                await channel.send(f"wait {remaining_time} longer before you make another wish...")
            except:
                pass
            return
        # END cooldown

        if selection == "me again":
            remove = True

        # remove all roles
        for key, role_id in self.role_map.items():
            try:
                old_role = guild.get_role(role_id)
                if old_role in my_member.roles:
                    await my_member.remove_roles(old_role)
            except:
                pass

        try:
            member_counts = Configuration.get_persistent_var(f"mischief_usage", dict())
            member_count = 0 if str(uid) not in member_counts else member_counts[str(uid)]
            member_counts[str(uid)] = member_count + 1
            Configuration.set_persistent_var("mischief_usage", member_counts)
            cooldown = Configuration.get_persistent_var("mischief_cooldown", dict())
            cooldown[str(uid)] = now
            Configuration.set_persistent_var("mischief_cooldown", cooldown)
        except Exception as e:
            await Utils.handle_exception("mischief role tracking error", self.bot, e)

        if not remove:
            # add the selected role
            new_role = guild.get_role(self.role_map[selection])
            await my_member.add_roles(new_role)

        if channel is not None:
            try:
                if remove:
                    await channel.send("fine, you're demoted!")
                else:
                    await channel.send(f"""Congratulations, you are now **{selection}**!! You can wish again in my DMs if you want!
You can also use the `!team_mischief` command right here to find out more""")
            except:
                pass

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # decrement role counts only for roles removed
        for role in before.roles:
            if role not in after.roles and str(role.id) in self.role_counts:
                self.role_counts[str(role.id)] = self.role_counts[str(role.id)] - 1
                # Logging.info(f"{after.display_name} --{role.name}")

        # increment role counts only for roles added
        for role in after.roles:
            if role not in before.roles and str(role.id) in self.role_counts:
                self.role_counts[str(role.id)] = self.role_counts[str(role.id)] + 1
                # Logging.info(f"{after.display_name} ++{role.name}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # decrement role counts for any tracked roles the departed member had
        for role in member.roles:
            if role.id in self.role_counts:
                self.role_counts[str(role.id)] = self.role_counts[str(role.id)] - 1


def setup(bot):
    bot.add_cog(Mischief(bot))
