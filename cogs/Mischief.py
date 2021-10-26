import re
from datetime import datetime

import discord
from discord import AllowedMentions
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Utils, Configuration, Logging


class Mischief(BaseCog):
    role_map = {
        "a bean": 902462040596164619,
        "a bird": 901960866226913340,
        "a buff moth": 902297335743279174,
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

    def __init__(self, bot):
        super().__init__(bot)
        for guild in self.bot.guilds:
            self.init_guild(guild)

    def init_guild(self, guild):
        pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        pass

    @commands.command()
    async def mischief(self, ctx):
        if not ctx.guild or not Utils.can_mod_official(ctx):
            return

        member_counts = Configuration.get_persistent_var(f"mischief_usage", dict())
        max_member_id = max(member_counts, key=member_counts.get)
        guild = Utils.get_home_guild()
        max_user: discord.Member = guild.get_member(int(max_member_id))
        await ctx.send(f"{len(member_counts)} people have gotten mischief roles. "
                       f"{max_user.mention} has spammed it the most, with {member_counts[max_member_id]} tries.",
                       allowed_mentions=AllowedMentions.none())

    @commands.command()
    async def team_mischief(self, ctx):
        if not ctx.guild or not Utils.can_mod_official(ctx):
            return

        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0xFFBD1C,
            title="Mischief!")

        for role_name, role_id in self.role_map.items():
            this_role: discord.role = ctx.guild.get_role(role_id)
            if this_role is None:
                continue
            embed.add_field(name=this_role.name, value=str(len(this_role.members)), inline=True)

        await ctx.send(embed=embed,
                       allowed_mentions=AllowedMentions.none())

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
        cooldown_time = 600
        cooldown = Configuration.get_persistent_var(f"mischief_cooldown", dict())
        member_last_access_time = 0 if str(uid) not in cooldown else cooldown[str(uid)]
        cooldown_elapsed = now - member_last_access_time
        remaining = cooldown_time - cooldown_elapsed

        if cooldown_elapsed < cooldown_time:
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


def setup(bot):
    bot.add_cog(Mischief(bot))
