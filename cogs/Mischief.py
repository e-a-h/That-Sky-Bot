import re
from datetime import datetime

import discord
from discord import AllowedMentions
from discord.ext import commands, tasks
from discord.ext.commands import BucketType

from cogs.BaseCog import BaseCog
from utils import Utils, Configuration, Logging


class Mischief(BaseCog):
    cooldown_time = 600
    role_map = {
        "a bean": 902462040596164619,
        "a bird": 901960866226913340,
        "a buff moth": 902297335743279174,
        "a bunny": 903083512951869530,
        "a butterfly": 901960358267326494,
        "a candle": 902327931680989285,
        "a cosmic manta": 901964236396314645,
        "a crab": 819720424992145458,
        "a flight guide": 902369136468959242,
        "a gratitude guide": 902455240404647948,
        "a jellyfish": 901960274754555924,
        "a koi fish": 902321584159723560,
        "a krilled skykid": 902346221665005629,
        "a manta": 901959573974425640,
        "a moth": 902294230679048222,
        "a pair of pants": 902446961414770728,
        "a prophecy guide": 902418537832906752,
        "a rhythm guide": 902330765352783912,
        "a shadow": 901960767119704064,
        "a spirit": 902293337028055111,
        "a tuna king": 827341301833531422,
        "a weasel": 902311536125673503,
        "an elder bird": 902307770815119370,
        "not a krill": 818924325633654824,
        "oreo": 902295610454069378,
        "a thatskybot": 902434147916709928,
        "totally a krill": 818978303243190302,
        "tuna king": 827341301833531422,
        "just a fish": 902616235005583400,
        "a dreams skater": 902648539014893680,
        "me again": 0
    }

    role_counts = {}

    def __init__(self, bot):
        super().__init__(bot)
        for guild in self.bot.guilds:
            self.init_guild(guild)
        self.periodic_task.start()

    def cog_unload(self):
        self.periodic_task.cancel()

    def init_guild(self, guild):
        # init guild-specific dicts and lists
        pass

    @tasks.loop(seconds=300)
    async def periodic_task(self):
        # periodic task to run while cog is loaded

        # remove expired cooldowns
        now = datetime.now().timestamp()
        cooldown = Configuration.get_persistent_var(f"mischief_cooldown", dict())

        try:
            # key for loaded dict is a string
            updated_cooldown = {}
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

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        pass

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
            return

        uid = message.author.id

        try:
            guild = Utils.get_home_guild()
            my_member: discord.Member = guild.get_member(uid)
            if my_member is None or len(message.content) > 60:
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
        pattern = re.compile(f"(skybot,? *)?({'|'.join(triggers)}) (.*)", re.I)
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
