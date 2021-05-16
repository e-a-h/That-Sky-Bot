
import asyncio
import copy
import re
import typing
from datetime import datetime

import discord
from discord.ext import commands, tasks
import io
import mimetypes
import requests
from discord.ext.commands import MemberConverter

import sky
from cogs.BaseCog import BaseCog
from utils import Configuration, Logging, Utils, Lang, Emoji


class Welcomer(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.welcome_talkers = dict()
        self.join_cooldown = dict()
        self.mute_new_members = dict()
        self.mute_minutes_old_account = dict()
        self.mute_minutes_new_account = dict()
        self.discord_verification_flow = dict()
        bot.loop.create_task(self.startup_cleanup())

    def cog_unload(self):
        self.check_cooldown.cancel()

    async def startup_cleanup(self):
        self.join_cooldown = Configuration.get_persistent_var("join_cooldown", dict())
        for guild in self.bot.guilds:
            self.init_guild(guild)
        self.check_cooldown.start()

    def init_guild(self, guild):
        self.set_verification_mode(guild)
        self.mute_minutes_old_account[guild.id] = Configuration.get_persistent_var(f"{guild.id}_mute_minutes_old_account", 10)
        self.mute_minutes_new_account[guild.id] = Configuration.get_persistent_var(f"{guild.id}_mute_minutes_new_account", 20)
        self.mute_new_members[guild.id] = Configuration.get_persistent_var(f"{guild.id}_mute_new_members", False)
        self.welcome_talkers[guild.id] = dict()
        if str(guild.id) not in self.join_cooldown:
            self.join_cooldown[str(guild.id)] = dict()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        try:
            # These may not be stored if mute config is never used:
            Configuration.del_persistent_var(f"{guild.id}_mute_new_members", True)
            Configuration.del_persistent_var(f"{guild.id}_mute_minutes_old_account", True)
            Configuration.del_persistent_var(f"{guild.id}_mute_minutes_new_account", True)
        except KeyError as e:
            pass
        del self.mute_minutes_old_account[guild.id]
        del self.mute_minutes_new_account[guild.id]
        del self.welcome_talkers[guild.id]
        del self.mute_new_members[guild.id]
        del self.discord_verification_flow[guild.id]
        del self.join_cooldown[str(guild.id)]

    def set_verification_mode(self, guild):
        # TODO: enforce channel permissions for entry_channel?
        # verification flow is on if entry channel is set
        ec = self.bot.get_guild_entry_channel(guild.id)

        self.discord_verification_flow[guild.id] = bool(ec)
        # Do not mute new members if verification flow is on.
        # Otherwise, mute new members UNLESS it's manually overridden
        self.mute_new_members[guild.id] = False if self.discord_verification_flow[guild.id] else \
            Configuration.get_persistent_var(f"{guild.id}_mute_new_members", True)

    def remove_member_from_cooldown(self, guildid, memberid):
        if str(guildid) in self.join_cooldown and str(memberid) in self.join_cooldown[str(guildid)]:
            del self.join_cooldown[str(guildid)][str(memberid)]
            Configuration.set_persistent_var("join_cooldown", self.join_cooldown)

    @tasks.loop(seconds=10.0)
    async def check_cooldown(self):
        m = self.bot.metrics
        mute_count = 0

        # check for members to unmute
        now = datetime.now().timestamp()

        for guild in self.bot.guilds:
            # report number of mutes to metrics server
            m.bot_welcome_mute.labels(guild_id=guild.id).set(len(self.join_cooldown[str(guild.id)]))

            # set verification periodically since channel setting can be changed in another cog
            self.set_verification_mode(guild)

            if self.discord_verification_flow[guild.id] and not self.join_cooldown[str(guild.id)]:
                # verification flow in effect, and nobody left to unmute.
                continue

            if not self.join_cooldown or not self.join_cooldown[str(guild.id)]:
                continue

            mute_role = guild.get_role(Configuration.get_var("muted_role"))
            my_mutes = copy.deepcopy(self.join_cooldown)
            log_channel = self.bot.get_config_channel(guild.id, Utils.log_channel)

            for user_id, join_time in my_mutes[str(guild.id)].items():
                try:
                    member = guild.get_member(int(user_id))
                    if member is None:
                        # user left server.
                        self.remove_member_from_cooldown(guild.id, user_id)
                        if log_channel is not None:
                            await log_channel.send(
                                f"I removed <@{user_id}> from mute cooldown because I think they left... did I do it right?")

                        continue

                    user_age = now - member.created_at.timestamp()
                    elapsed = int(now - join_time)
                    cooldown_time = 60 * self.mute_minutes_old_account[guild.id]  # 10 minutes default
                    if user_age < 60 * 60 * 24:  # 1 day
                        cooldown_time = 60 * self.mute_minutes_new_account[guild.id]  # 20 minutes default for new users

                    if elapsed > cooldown_time:
                        # member has waited long enough
                        if mute_role in member.roles:
                            await member.remove_roles(mute_role)
                        self.remove_member_from_cooldown(guild.id, user_id)

                except Exception as e:
                    # error with member. not sure why. log it and remove from cooldown to prevent repeats
                    self.remove_member_from_cooldown(guild.id, user_id)
                    await Utils.handle_exception(f"Failed to unmute new member {user_id} in guild {guild.id}",
                                                 self.bot, e)
                    if log_channel is not None:
                        await log_channel.send(f"Failed to unmute <@{user_id}>. Maybe someone should look into that?")
                    continue

    async def cog_check(self, ctx):
        if ctx.guild is None:
            return False
        return ctx.author.guild_permissions.ban_members

    def fetch_recent(self, time_delta: int = 1):
        """
        fetch all members who have joined within a certain number of hours

        time_delta: number of hours within which members have joined
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
                                 f"- joined {int((now - member.joined_at.timestamp()) / 60 / 60)} hours ago"

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

            # Send welcome message in configured language. default to english
            if welcome_channel and rules_channel:
                txt = Lang.get_locale_string("welcome/welcome_msg",
                                             Configuration.get_var('broadcast_locale', 'en_US'),
                                             user=member.mention,
                                             rules_channel=rules_channel.mention,
                                             accept_emoji=Emoji.get_chat_emoji('CANDLE'))
                if self.mute_new_members[member.guild.id]:
                    # add mute notification if mute for new members is on
                    mute_txt = Lang.get_locale_string("welcome/welcome_mute_msg",
                                                      Configuration.get_var('broadcast_locale', 'en_US'))
                    txt = f"{txt}\n{mute_txt}"
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
        """Configure welcome message settings"""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @welcome.command(aliases=['verify'])
    @commands.guild_only()
    @sky.can_admin()
    async def verify_invited(self, ctx, *, member_list=""):
        with ctx.channel.typing():
            await ctx.send("This might take a while. rate limiting stops me searching all members quickly...")
            attachment_links = [str(a.url) for a in ctx.message.attachments]
            if attachment_links:
                if len(attachment_links) != 1:
                    await ctx.send(f"I can only handle one attachment for this command (or past in a list of names)")
                    return
                url = str(attachment_links[0])
                # download attachment and put it in a buffer
                u = requests.get(url)
                content_type = u.headers['content-type']
                extension = mimetypes.guess_extension(content_type)
                buffer = io.BytesIO()
                buffer.write(u.content)
                buffer.seek(0)  # start reading at the beginning
                with buffer as f:
                    names = [i.decode('UTF-8').strip() for i in f.readlines()]
            else:
                names = [i.strip() for i in member_list.splitlines()]

            members = []
            my_converter = MemberConverter()
            for name in names:
                try:
                    a_member = await my_converter.convert(ctx, name)
                    members.append(a_member)
                except Exception as e:
                    pass

            sus = []
            for member in ctx.guild.members:
                if member not in members:
                    sus.append(member)

            if not members:
                await ctx.send("You didn't give me any names to check. Try again with a list or file")
                return

            if sus:
                sus_list = [f"{member.display_name}#{member.discriminator} ({member.id})" for member in sus]
                sus_list = '\n'.join(sus_list)
                buffer = io.StringIO()
                buffer.write(sus_list)
                buffer.seek(0)

                await ctx.send(
                    content=f"yo, these members aren't on the approved list",
                    file=discord.File(buffer, f"impostors.txt"))
            else:
                await ctx.send("OMG, nobody sneaked into the server while I wasn't looking!")

    # TODO:
    #  store members invites
    #  store verified members
    #  match invites to verified members

    # @welcome.group(name="members", invoke_without_command=True)
    # @commands.guild_only()
    # @sky.can_admin()
    # async def members(self, ctx):
    #     # todo: list?
    #     pass
    #
    # @members.command()
    # @commands.guild_only()
    # @sky.can_admin()
    # async def remove(self, ctx, *, member_list):
    #     # todo: add individual by br-separated list, one, or by csv
    #     pass
    #
    # @members.command()
    # @commands.guild_only()
    # @sky.can_admin()
    # async def verify(self, ctx, *, member_list):
    #     # todo: add individual by br-separated list, one, or by csv
    #     pass
    #
    # @members.command()
    # @commands.guild_only()
    # @sky.can_admin()
    # async def verify_all(self, ctx):
    #     # todo: check all members whether they are on the list
    #     pass

    @welcome.command(aliases=['configmute', 'muteconfig', 'configure_mute', 'mute_configure', 'mute'])
    @commands.guild_only()
    async def mute_config(self, ctx, active: bool = None, mute_minutes_old: int = 10, mute_minutes_new: int = 20):
        """
        Mute settings for new members

        active: mute on or off
        mute_minutes_old: how long (minutes) to mute established accounts (default 10)
        mute_minutes_new: how long (minutes) to mute accounts < 1 day old (default 20)
        """
        self.set_verification_mode(ctx.guild)
        if self.discord_verification_flow[ctx.guild.id]:
            # discord verification flow precludes new-member muting
            await ctx.send("""
            Discord verification flow is in effect. Mute is configured in discord moderation settings.
            To enable skybot muting, unset entry_channel: `!channel_config set entry_channel 0`
            """)
            return

        if active is not None:
            self.mute_new_members[ctx.guild.id] = active
            self.mute_minutes_old_account[ctx.guild.id] = mute_minutes_old
            self.mute_minutes_new_account[ctx.guild.id] = mute_minutes_new
            Configuration.set_persistent_var(f"{ctx.guild.id}_mute_new_members", active)
            Configuration.set_persistent_var(f"{ctx.guild.id}_mute_minutes_old_account", mute_minutes_old)
            Configuration.set_persistent_var(f"{ctx.guild.id}_mute_minutes_new_account", mute_minutes_new)

        status = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("welcome/mute_settings_title", ctx, server_name=ctx.guild.name))

        status.add_field(name="Mute new members",
                         value=f"**{'ON' if self.mute_new_members[ctx.guild.id] else 'OFF'}**",
                         inline=False)
        status.add_field(name="Mute duration",
                         value=f"{self.mute_minutes_old_account[ctx.guild.id]} minutes",
                         inline=False)
        status.add_field(name="New account mute duration\n(< 1 day old) ",
                         value=f"{self.mute_minutes_new_account[ctx.guild.id]} minutes",
                         inline=False)
        await ctx.send(embed=status)

    @welcome.command()
    @commands.guild_only()
    async def purge_mutes(self, ctx):
        mute_role = ctx.guild.get_role(Configuration.get_var("muted_role"))
        unmuted_members = list()
        purge_list = copy.deepcopy(self.join_cooldown)
        for user_id in purge_list[str(ctx.guild.id)]:
            try:
                member = ctx.guild.get_member(int(user_id))
                if mute_role in member.roles:
                    await member.remove_roles(mute_role)
                self.remove_member_from_cooldown(ctx.guild.id, user_id)
                unmuted_members.append(Utils.get_member_log_name(member))
            except Exception as e:
                pass
        member_list = '\n'.join(unmuted_members)
        if member_list:
            await ctx.send(f"Ok, I unmuted these members:\n{member_list}")
        else:
            await ctx.send(f"nobody to unmute")

    def muted_mode(argument):
        modes = [0, 1, 2, 3]

        def fail():
            nonlocal modes
            raise discord.ext.commands.BadArgument(f'mode must be one of {modes}')

        try:
            mode = int(argument)
        except ValueError:
            fail()
            return

        if mode in modes:
            return mode
        fail()

    @welcome.command(aliases=["list", "muted"])
    @commands.guild_only()
    async def list_muted(self, ctx, mode: muted_mode = 1):
        """
        List muted members

        List all members who are muted. Separate join-cooldown members from regular mutes.
        Also list un-muted members who are somehow still on the cooldown list just in case.

        mode: 1. List muted members on join-cooldown
              2. List muted members NOT on join-cooldown
              3. List join-cooldown members who are NOT muted
              0. List all
        """
        muted_role = ctx.guild.get_role(Configuration.get_var("muted_role"))
        cooling_down = []
        untracked_mute = []
        on_cooldown_not_muted = []
        for member in ctx.guild.members:
            if str(member.id) in self.join_cooldown[str(ctx.guild.id)]:
                if muted_role in member.roles:
                    cooling_down.append(Utils.get_member_log_name(member))
                else:
                    on_cooldown_not_muted.append(Utils.get_member_log_name(member))
            else:
                if muted_role in member.roles:
                    untracked_mute.append(Utils.get_member_log_name(member))
                else:
                    # not on cooldown, not muted
                    pass
        if mode in [0, 1]:
            if not cooling_down:
                await ctx.send("No members on join-cooldown")
                return
            await ctx.send(f"**Members who are muted for join-cooldown:**")
            msg = '\n'.join(cooling_down)
            pages = Utils.paginate(msg)
            for page in pages:
                await ctx.send(page)
        if mode in [0, 2]:
            if not untracked_mute:
                await ctx.send("No non-cooldown mutes")
                return
            await ctx.send(f"**Members who are muted, but not on join-cooldown:**")
            msg = '\n'.join(untracked_mute)
            pages = Utils.paginate(msg)
            for page in pages:
                await ctx.send(page)
        if mode in [0, 3]:
            if not on_cooldown_not_muted:
                await ctx.send("No errant unmuted cooldown members")
                return
            await ctx.send(f"**Members on the join-cooldown list WITHOUT mute**")
            msg = '\n'.join(on_cooldown_not_muted)
            pages = Utils.paginate(msg)
            for page in pages:
                await ctx.send(page)
        if not cooling_down and not untracked_mute and not on_cooldown_not_muted:
            await ctx.send("There are no mutes and nothing tracked by welcomer.")

    @welcome.command(aliases=["count", "cr"])
    @commands.guild_only()
    async def count_recent(self, ctx, time_delta: int = 1):
        """
        Count members who have joined within [time_delta] hours

        time_delta: number of hours to check for recent joins
        """
        await ctx.send(f"counting members who joined in the last {time_delta} hours...")
        recent = self.fetch_recent(time_delta)
        content = f"There are {len(recent['unverified'])} members who joined within {time_delta} hours, but who still haven't verified" + '\n'
        content += f"There are {len(recent['too_old'])} unverified members who joined more than {time_delta} hours ago" + '\n'
        content += f"There are {len(recent['verified'])} verified members"
        await ctx.send(content)

    @welcome.command(aliases=["shadows", "count_nonmembers"])
    @commands.guild_only()
    async def count_shadows(self, ctx):
        """
        Count members who have shadow role
        """
        members = self.bot.get_all_members()
        nonmember_role = ctx.guild.get_role(Configuration.get_var("nonmember_role"))

        await ctx.send(f"counting members who have the shadow role...")
        count = 0
        multi_role_count = 0
        no_role_count = 0
        for member in members:
            if member.bot or member.guild.id != ctx.guild.id:
                # Don't count bots or members of other guilds
                continue

            if len(member.roles) == 0:
                no_role_count = no_role_count + 1

            if nonmember_role in member.roles:
                count = count + 1
                if len(member.roles) > 1:
                    # count members who have shadow role AND other role(s)
                    multi_role_count = multi_role_count + 1

        content = f"There are {count} members with \"{nonmember_role.name}\" role.\n"
        content += f"Among them, {multi_role_count} members have \"{nonmember_role.name}\" role *and* 1 or more other roles.\n"
        content += f"There are {no_role_count} members with no roles assigned."
        await ctx.send(content)

    @welcome.command(aliases=["darken", "darkness", "give_shadows"])
    @commands.guild_only()
    async def give_shadow(self, ctx, time_delta: typing.Optional[int] = 1, add_role: bool = False):
        """
        Add non-member role to members with no role

        time_delta: how far back (in hours) to search for members with no roles
        add_role:
        """
        recent = self.fetch_non_role(time_delta)
        string_name = 'welcome/darkness' if (len(recent['unverified']) == 1) else 'welcome/darkness_plural'
        await ctx.send(Lang.get_locale_string(string_name, ctx,
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
            await ctx.send(Lang.get_locale_string(string_name, ctx, count=count))

    @welcome.command()
    @commands.guild_only()
    async def recent(self, ctx, time_delta: typing.Optional[int] = 1, ping: bool = False):
        """
        Manually welcome all members who have joined within a certain number of hours

        time_delta: number of hours within which members have joined
        ping: boolean flag, indicates whether to send welcome to members in welcome channel
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
    async def on_member_update(self, before, after):
        try:
            if before.pending and not after.pending:
                # member just accepted rules

                # don't add a role or this defeats the cool-down.
                # wait for member to talk, then add a role.

                # TODO: metrics logging

                # member_role = after.guild.get_role(Configuration.get_var("member_role"))
                # await after.add_roles(member_role)
                # print(f"{after.display_name} is a member now")
                pass
        except Exception as e:
            pass

        try:
            # Enforce member role on any role changes - in case other bot assigns a role.
            # TODO: should this be configurable on|off?
            member_role = before.guild.get_role(Configuration.get_var("member_role"))
            member_before = member_role in before.roles
            member_after = member_role in after.roles

            if before.roles != after.roles:
                if (not member_before and not member_after) or (member_before and not member_after):
                    await after.add_roles(member_role)
        except Exception as e:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # clear rules reactions
        roles = Configuration.get_var("roles")
        guild = self.bot.get_guild(member.guild.id)

        self.remove_member_from_cooldown(guild.id, member.id)

        rules_channel = self.bot.get_config_channel(guild.id, Utils.rules_channel)
        rules_message_id = Configuration.get_var('rules_react_message_id')
        try:
            rules = await rules_channel.fetch_message(rules_message_id)
        except Exception as e:
            return

        for reaction, role_id in roles.items():
            try:
                await rules.remove_reaction(reaction, member)
            except Exception as e:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if self.mute_new_members[member.guild.id] and not self.discord_verification_flow[member.guild.id]:
            self.bot.loop.create_task(self.mute_new_member(member))

        if self.discord_verification_flow[member.guild.id]:
            # do not welcome new members when using discord verification
            # set entry_channel to use discord verification
            return

        # Only send welcomes for configured guild i.e. sky official
        # TODO: retool to allow any guild to welcome members?
        guild = self.bot.get_guild(Configuration.get_var("guild_id"))
        if member.guild.id != guild.id:
            return

        # add the nonmember role
        nonmember_role = guild.get_role(Configuration.get_var("nonmember_role"))
        await member.add_roles(nonmember_role)

        # send the welcome message
        await self.send_welcome(member)

    async def member_verify_action(self, message):
        entry_channel = self.bot.get_config_channel(message.guild.id, Utils.entry_channel)
        if entry_channel and message.channel.id == entry_channel.id:
            try:
                # delete triggering message from entry channel
                await message.delete()
                # add nonmember role to reveal welcome/rules channels
                nonmember_role = message.guild.get_role(Configuration.get_var("nonmember_role"))
                await message.author.add_roles(nonmember_role)
                # send welcome prompt in welcome channel
                await self.send_welcome(message.author)
            except Exception as e:
                # TODO: specify exceptions
                pass
            return True
        # No entry channel or not in channel.
        return False

    async def member_completed_join(self, member):
        # member role is already given by reaction handler
        # nonmember role is already taken by reaction handler
        pass

    async def mute_new_member(self, member):
        # is this feature turned on?
        if not self.mute_new_members[member.guild.id]:
            return

        # give other bots a chance to perform other actions first (like mute)
        await asyncio.sleep(0.5)
        # refresh member for up-to-date roles
        member = member.guild.get_member(member.id)

        mute_role = member.guild.get_role(Configuration.get_var("muted_role"))

        # only add mute if it hasn't already been added. This allows other mod-bots (gearbot) to mute re-joined members
        # and not interfere by allowing skybot to automatically un-muting later.
        if mute_role not in member.roles:
            self.join_cooldown[str(member.guild.id)][str(member.id)] = datetime.now().timestamp()
            Configuration.set_persistent_var("join_cooldown", self.join_cooldown)
            log_channel = self.bot.get_config_channel(member.guild.id, Utils.log_channel)
            if mute_role:
                # Auto-mute new members, pending cooldown
                await member.add_roles(mute_role)

    @commands.command()
    async def check_member_name(self, ctx, *, name: str):
        matches = []
        for member in self.bot.get_all_members():
            if member.guild.id != ctx.guild.id:
                continue
            display_name = member.display_name
            if re.fullmatch(re.escape(name), re.escape(display_name), re.IGNORECASE) is not None:
                matches.append(member)
        if matches:
            embed = discord.Embed(
                timestamp=ctx.message.created_at,
                color=0x663399,
                title=f"Display-names that match \"{name}\" in *{ctx.guild.name}* server")
            for member in matches:
                embed.add_field(name=member.display_name,
                                value=f"{member.name}#{member.discriminator} ({member.id})",
                                inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"I found no names matching \"{name}\" in this guild.")

        # TODO: check existing member display-names for exact duplicates
        #  if match, log in log channel
        #  if configured, DM member informing them about impersonating, ask them to change, refer them to mods
        pass

    @commands.command(aliases=['set_rules_id', 'setrulesid'])
    @commands.guild_only()
    async def set_rules_react_message_id(self, ctx, message_id: int):
        """
        Set the message ID of the rules react-to-join message

        Setting rules message ID also clears reactions, and may be helpful if discord glitches from too many reacts

        message_id: Message id of rules react message
        """
        rules_channel = self.bot.get_config_channel(ctx.guild.id, Utils.rules_channel)
        if message_id and not rules_channel:
            ctx.send('Rules channel must be set in order to set rules message. Try `!channel_config set rules_channel [id]`')

        # clear old reactions
        rules_message_id = Configuration.get_var('rules_react_message_id')
        try:
            # Un-setting rules message. Clear reactions from the old one.
            old_rules = await rules_channel.fetch_message(rules_message_id)
            await old_rules.clear_reactions()
            await ctx.send(f"Cleared reactions from:\n{old_rules.jump_url}")
            # TODO: make this guild-specific
        except Exception as e:
            await ctx.send(f"Failed to clear existing rules reactions")

        try:
            Configuration.MASTER_CONFIG['rules_react_message_id'] = message_id
            Configuration.save()
        except Exception as e:
            await ctx.send(f"Failed while saving configuration. Operation will continue, but check the logs...")

        if message_id == 0:
            if rules_message_id == 0:
                await ctx.send(f"Rules message is already unset")
            return

        try:
            new_rules = await rules_channel.fetch_message(message_id)
            roles = Configuration.get_var("roles")
            await new_rules.clear_reactions()
            for emoji, role_id in roles.items():
                # if not Emoji.is_emoji_defined(emoji):
                #     continue
                # emoji = Emoji.get_chat_emoji(emoji)
                await new_rules.add_reaction(emoji)
            await ctx.send(f"Rules message set to {message_id} in channel {rules_channel.mention}")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            await ctx.send(f"Could not find message id {message_id} in channel {rules_channel.mention}")

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not hasattr(message.author, "guild"):
            return

        welcome_channel = self.bot.get_config_channel(message.guild.id, Utils.welcome_channel)
        rules_channel = self.bot.get_config_channel(message.guild.id, Utils.rules_channel)
        log_channel = self.bot.get_config_channel(message.guild.id, Utils.log_channel)
        member_role = message.guild.get_role(self.bot.get_guild_db_config(message.guild.id).memberrole)
        nonmember_role = message.guild.get_role(self.bot.get_guild_db_config(message.guild.id).nonmemberrole)

        if message.author.id == 349977940198555660:  # is gearbot
            pattern = re.compile(r'\(``(\d+)``\) has re-joined the server before their mute expired')
            match = re.search(pattern, message.content)
            if match:
                user_id = int(match[1])
                # gearbot is handling it. never unmute this user
                self.remove_member_from_cooldown(message.guild.id, user_id)
                muted_member = message.guild.get_member(user_id)
                muted_member_name = Utils.get_member_log_name(muted_member)
                await log_channel.send(
                    f'''
                    Gearbot re-applied mute when member re-joined: {muted_member_name}
                    I won't try to unmute them later.
                    ''')
                return

        if message.author.guild_permissions.mute_members or \
                await self.member_verify_action(message) or \
                (member_role is not None and member_role in message.author.roles):
            # is a mod or
            # verification flow triggered. no further processing or
            # message from regular member. no action for welcomer to take.
            return

        # ignore when channels not configured
        if not welcome_channel or not rules_channel or message.channel.id != welcome_channel.id:
            if member_role is not None and member_role not in message.author.roles:
                # nonmember speaking somewhere other than welcome channel? Maybe we're not using the
                # welcome channel anymore? or something else went wrong... give them member role.
                try:
                    await message.author.add_roles(member_role)
                    if nonmember_role is not None and nonmember_role in message.author.roles:
                        Logging.info(f"{Utils.get_member_log_name(message.author)} - had shadow role when speaking. removing it!")
                        await message.author.remove_roles(nonmember_role)
                except Exception as e:
                    try:
                        Logging.info(f"message: {message.content}")
                        Logging.info(f"author id: {message.author.id}")
                    except Exception as ee:
                        pass
                    await Utils.handle_exception("member join exception", self.bot, e)
            return

        # Only act on messages in welcome channel from here on
        # Nonmember will only be warned once every 10 minutes that they are speaking in welcome channel
        now = datetime.now().timestamp()
        then = 0
        grace_period = 10 * 60  # 10 minutes

        try:
            was_welcomed = self.welcome_talkers[message.guild.id][message.author.id]
            then = was_welcomed + grace_period
        except Exception as ex:
            # TODO: refine exception. KeyError only?
            pass

        if then > now:
            # grace period has not expired. Do not warn member again yet.
            # print("it hasn't been 10 minutes...")
            return

        ctx = self.bot.get_context(message)

        # record the time so member won't be pinged again too soon if they keep talking
        self.welcome_talkers[message.guild.id][message.author.id] = now
        await welcome_channel.send(Lang.get_locale_string("welcome/welcome_help", ctx,
                                                          author=message.author.mention,
                                                          rules_channel=rules_channel.mention))
        # ping log channel with detail
        if log_channel:
            await log_channel.send(f"{Utils.get_member_log_name(message.author)} "
                                   f"spoke in {welcome_channel.mention} ```{message.content}```")

    async def handle_reaction_change(self, t, reaction, user_id):
        roles = Configuration.get_var("roles")
        if reaction in roles:
            guild = self.bot.get_guild(Configuration.get_var("guild_id"))
            role = guild.get_role(roles[reaction])
            member_role = guild.get_role(Configuration.get_var("member_role"))
            nonmember_role = guild.get_role(Configuration.get_var("nonmember_role"))
            member = guild.get_member(user_id)

            if member is None:
                return

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
