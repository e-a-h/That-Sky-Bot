import asyncio
from datetime import date, datetime

import discord
import typing
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Configuration, Logging, Utils, Lang, Emoji


class Welcomer(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.welcome_talkers = dict()
        self.join_cooldown = dict()
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        for guild in self.bot.guilds:
            my_friends = set()
            self.welcome_talkers[guild.id] = dict()
            self.join_cooldown[guild.id] = dict()

    async def check_cooldown(self, user):
        now = datetime.now()
        user_age = now - user.created_at
        await asyncio.sleep(600)
        for guild in self.bot.guilds:
            mute_role = guild.get_role(Configuration.get_var("muted_role"))
            for user.id, join_time in self.join_cooldown[guild.id].items():
                elapsed = now - join_time
                cooldown_time = 600  # 10 minutes
                if user_age.seconds < 60*60*24:  # 1 day
                    cooldown_time = 1200  # 20 minutes for new users
                if elapsed > cooldown_time:
                    user.remove_roles(mute_role)
                    
    async def cog_check(self, ctx):
        if not hasattr(ctx.author, 'guild'):
            return False
        return ctx.author.guild_permissions.ban_members

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.welcome_talkers[guild.id] = dict()
        self.join_cooldown[guild.id] = dict()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.welcome_talkers[guild.id]
        del self.join_cooldown[guild.id]

    def fetch_recent(self, time_delta: int = 1):
        """
        fetch all members who have joined within a certain number of hours
        :param ctx:
        :param time_delta: number of hours within which members have joined
        :return:
        """
        now = datetime.now().timestamp()
        then = now - (time_delta * 60 * 60)
        members = self.bot.get_all_members()
        unverified_members = []
        too_old_members = []
        verified_members = []
        for member in members:
            if member.bot or member.guild.id != Configuration.get_var("guild_id"):
                # Don't count bots or people who aren't in primary server
                continue

            # guild members, non-bot:
            nick = ""
            if member.nick:
                nick = f'*"{member.nick}"*'
            member_description = f"{member.name}#{member.discriminator} ({member.id}) {nick} " \
                                 f"- joined {int((now-member.joined_at.timestamp())/60/60)} hours ago"

            if self.is_member_verified(member):
                verified_members.append([member, member_description])
                continue

            if member.joined_at.timestamp() > then:
                # Joined since X hours ago
                unverified_members.append([member, member_description])
            else:
                # unverified, but joined a long time ago
                too_old_members.append([member, member_description])
        return {
            "unverified": unverified_members,
            "verified": verified_members,
            "too_old": too_old_members
        }

    def fetch_non_role(self, time_delta: int = 1):
        # fetch members without the verified role
        recent = self.fetch_recent(time_delta)

        # narrow results to members who ALSO do not have the unverified role
        unverified = []
        for member in recent['unverified']:
            if not self.is_member_unverified(member[0]):
                unverified.append(member[0])
        too_old = []
        for member in recent['too_old']:
            if not self.is_member_unverified(member[0]):
                too_old.append(member[0])
        return {
            "unverified": unverified,
            "too_old": too_old
        }

    def is_member_verified(self, member):
        try:
            guild = self.bot.get_guild(Configuration.get_var("guild_id"))
            if member.guild.id != guild.id:
                return True  # non-members are "verified" so we don't try to interact with them
            member_role = guild.get_role(Configuration.get_var("member_role"))
            if member_role not in member.roles:
                return False
            return True
        except Exception as ex:
            return True  # exceptions are "verified" so we don't try to interact with them *again*

    def is_member_unverified(self, member):
        try:
            guild = self.bot.get_guild(Configuration.get_var("guild_id"))
            if member.guild.id != guild.id:
                return True  # non-members are "verified" so we don't try to interact with them
            nonmember_role = guild.get_role(Configuration.get_var("nonmember_role"))
            if nonmember_role not in member.roles:
                return False
            return True
        except Exception as ex:
            return True  # exceptions are "verified" so we don't try to interact with them *again*

    async def send_welcome(self, member):
        guild = self.bot.get_guild(Configuration.get_var("guild_id"))
        if member.guild.id != guild.id or self.is_member_verified(member):
            return False

        try:
            welcome_channel = self.bot.get_config_channel(guild.id, Utils.welcome_channel)
            rules_channel = self.bot.get_config_channel(guild.id, Utils.rules_channel)

            if welcome_channel and rules_channel:
                txt = Lang.get_string("welcome/welcome_msg",
                                      user=member.mention,
                                      rules_channel=rules_channel.mention,
                                      accept_emoji=Emoji.get_chat_emoji('CANDLE'))
                await welcome_channel.send(txt)
                return True
        except Exception as ex:
            Logging.info(f"failed to welcome {member.id}")
            Logging.error(ex)
            raise ex
        return False

    @commands.group(name="welcome", invoke_without_command=True)
    @commands.guild_only()
    async def welcome(self, ctx):
        await ctx.send(Lang.get_string('welcome/help'))

    @welcome.command(aliases=["count", "cr"])
    @commands.guild_only()
    async def count_recent(self, ctx, time_delta: int = 1):
        await ctx.send(f"counting members who joined in the last {time_delta} hours...")
        recent = self.fetch_recent(time_delta)
        content = f"There are {len(recent['unverified'])} members who joined within {time_delta} hours, but who still haven't verified" + '\n'
        content += f"There are {len(recent['too_old'])} unverified members who joined more than {time_delta} hours ago" + '\n'
        content += f"There are {len(recent['verified'])} verified members"
        await ctx.send(content)

    @welcome.command(aliases=["darken", "darkness", "give_shadows"])
    @commands.guild_only()
    async def give_shadow(self, ctx, time_delta: typing.Optional[int] = 1, add_role: bool = False):
        recent = self.fetch_non_role(time_delta)
        string_name = 'welcome/darkness' if (len(recent['unverified']) == 1) else 'welcome/darkness_plural'
        await ctx.send(Lang.get_string(string_name,
                                       unverified=len(recent['unverified']),
                                       time_delta=time_delta,
                                       too_old=len(recent['too_old'])))
        if add_role:
            nonmember_role = ctx.guild.get_role(Configuration.get_var("nonmember_role"))
            # slowly add roles, since this may be a large number of members
            count = 0
            try:
                for member in recent['unverified']:
                    await member.add_roles(nonmember_role)
                    count += 1
                    await asyncio.sleep(0.3)
            except Exception as ex:
                await Utils.handle_exception("problem adding shadow role", self, ex)
            string_name = 'welcome/darkened' if count == 1 else 'welcome/darkened_plural'
            await ctx.send(Lang.get_string(string_name, count=count))

    @welcome.command(aliases=["nonmember", "shadows", "shadow"])
    @commands.guild_only()
    async def ping_unverified(self, ctx):
        guild = self.bot.get_guild(Configuration.get_var("guild_id"))
        try:
            nonmember_role = guild.get_role(Configuration.get_var("nonmember_role"))
            txt = Lang.get_string("welcome/welcome_msg")

            welcome_channel = self.bot.get_config_channel(guild.id, Utils.welcome_channel)
            rules_channel = self.bot.get_config_channel(guild.id, Utils.rules_channel)

            if welcome_channel and rules_channel:
                txt = Lang.get_string("welcome/welcome_msg",
                                      user=nonmember_role.mention,
                                      rules_channel=rules_channel.mention,
                                      accept_emoji=Emoji.get_chat_emoji('CANDLE'))

                await nonmember_role.edit(mentionable=True)
                await welcome_channel.send(txt)
                await nonmember_role.edit(mentionable=False)
                return True
        except Exception as ex:
            Logging.info(f"failed to welcome unverified role.")
            Logging.error(ex)
            raise ex
        return False

    @welcome.command()
    @commands.guild_only()
    async def recent(self, ctx, time_delta: typing.Optional[int] = 1, ping: bool = False):
        """
        Manually welcome all members who have joined within a certain number of hours
        :param ctx:
        :param time_delta: number of hours within which members have joined
        :param ping: send welcome to members in welcome channel
        :return:
        """
        await ctx.send(f"counting members who joined in the last {time_delta} hours...")
        recent = self.fetch_recent(time_delta)

        verified = recent['verified']
        unverified = recent['unverified']
        too_old = recent['too_old']

        if not unverified:
            await ctx.send(f"Couldn't find any unverified member who has joined within {time_delta} hours")
            return

        welcomed = []
        not_welcomed = []
        failed_welcome = []
        pending_welcome = []
        for member in unverified:
            if not ping:
                pending_welcome.append(member[1])
                continue
            try:
                sent = await self.send_welcome(member[0])
                await asyncio.sleep(0.3)
            except Exception as ex:
                sent = False
            if sent:
                welcomed.append(member[1])
            else:
                failed_welcome.append(member[1])

        failed_lists = list(Utils.split_list(not_welcomed, 50))

        content = f"**Ignored {len(verified)} members who already have a verified role**" + '\n'
        content += f"**There are {len(too_old)} unverified members who joined too long ago**" + '\n'
        if ping:
            content += f"**Welcomed {len(welcomed)} members**" + '\n'
        else:
            content += f"**There are  {len(unverified)} members to welcome**" + '\n'

        for members in failed_lists:
            content += "**Failed to welcome these members:**\n " + '\n '.join(members)

        await ctx.send(content)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = self.bot.get_guild(Configuration.get_var("guild_id"))
        if member.guild.id != guild.id:
            return

        mute_role = guild.get_role(Configuration.get_var("muted_role"))
        # Auto-mute new members, pending cooldown
        await member.add_roles(mute_role)
        self.join_cooldown[guild.id][member.id] = datetime.now()
        await self.send_welcome(member)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        react_user_id = event.user_id
        rules_message_id = Configuration.get_var('rules_react_message_id')
        if react_user_id != self.bot.user.id and event.message_id == rules_message_id:
            await self.handle_reaction_change("add", str(event.emoji), react_user_id)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, event):
        react_user_id = event.user_id
        rules_message_id = Configuration.get_var('rules_react_message_id')
        if react_user_id != self.bot.user.id and event.message_id == rules_message_id:
            await self.handle_reaction_change("remove", str(event.emoji), react_user_id)

    @commands.guild_only()
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.author.guild_permissions.mute_members:
            return

        member_role = message.guild.get_role(Configuration.get_var("member_role"))
        if member_role in message.author.roles:
            return

        welcome_channel = self.bot.get_config_channel(message.guild.id, Utils.welcome_channel)
        rules_channel = self.bot.get_config_channel(message.guild.id, Utils.rules_channel)
        log_channel = self.bot.get_config_channel(message.guild.id, Utils.log_channel)
        if not welcome_channel or not rules_channel:
            # ignore when channels not configured
            return

        if message.channel.id != welcome_channel.id:
            return

        now = datetime.now().timestamp()
        then = 0
        grace_period = 10 * 60  # 3 minutes

        try:
            was_welcomed = self.welcome_talkers[message.guild.id][message.author.id]
            then = was_welcomed + grace_period
        except Exception as ex:
            pass

        if then > now:
            # print("it hasn't been 10 minutes...")
            return

        # record the time so member won't be pinged again too soon if they keep talking
        self.welcome_talkers[message.guild.id][message.author.id] = now
        await welcome_channel.send(Lang.get_string("welcome/welcome_help",
                                                   author=message.author.mention,
                                                   rules_channel=rules_channel.mention))
        # ping log channel with detail
        if log_channel:
            await log_channel.send(f"{message.author.mention} spoke in {welcome_channel.mention} ```{message.content}```")

    async def handle_reaction_change(self, t, reaction, user_id):
        roles = Configuration.get_var("roles")
        if reaction in roles:
            guild = self.bot.get_guild(Configuration.get_var("guild_id"))
            role = guild.get_role(roles[reaction])
            member_role = guild.get_role(Configuration.get_var("member_role"))
            nonmember_role = guild.get_role(Configuration.get_var("nonmember_role"))
            member = guild.get_member(user_id)
            action = getattr(member, f"{t}_roles")
            try:
                await action(role)
                # if acting on member role, toggle corresponding nonmember role
                if role is member_role:
                    if t == 'add':
                        await member.remove_roles(nonmember_role)
                    else:
                        await member.add_roles(nonmember_role)
            except Exception as ex:
                Logging.info("failed")
                Logging.error(ex)
                raise ex


def setup(bot):
    bot.add_cog(Welcomer(bot))
