import asyncio
import copy
import re
import typing
from datetime import datetime

import discord
from discord.ext import commands, tasks

from cogs.BaseCog import BaseCog
from utils import Configuration, Logging, Utils, Lang, Emoji


class Welcomer(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.welcome_talkers = dict()
        self.join_cooldown = dict()
        self.mute_new_members = True
        self.mute_minutes_old_account = 10
        self.mute_minutes_new_account = 20
        self.discord_verification_flow = False
        bot.loop.create_task(self.startup_cleanup())

    def cog_unload(self):
        self.check_cooldown.cancel()

    async def startup_cleanup(self):
        self.join_cooldown = Configuration.get_persistent_var("join_cooldown", dict())
        for guild in self.bot.guilds:
            self.set_verification_mode(guild)
            self.mute_minutes_old_account = Configuration.get_persistent_var(f"{guild.id}_mute_minutes_old_account", 10)
            self.mute_minutes_new_account = Configuration.get_persistent_var(f"{guild.id}_mute_minutes_new_account", 20)
            self.welcome_talkers[guild.id] = dict()
            if str(guild.id) not in self.join_cooldown:
                self.join_cooldown[str(guild.id)] = dict()
        self.check_cooldown.start()

    def set_verification_mode(self, guild):
        # TODO: enforce channel permissions for entry_channel?
        # verification flow is on if entry channel is set
        self.discord_verification_flow = bool(self.bot.get_config_channel(guild.id, Utils.entry_channel))
        # Do not mute new members if verification flow is on.
        # Otherwise, mute new members UNLESS it's manually overridden
        self.mute_new_members = False if self.discord_verification_flow else \
            Configuration.get_persistent_var(f"{guild.id}_mute_new_members", True)

    @tasks.loop(seconds=10.0)
    async def check_cooldown(self):
        m = self.bot.metrics
        mute_count = 0

        # check for members to unmute
        now = datetime.now().timestamp()

        def remove_member_from_cooldown(guildid, memberid):
            del self.join_cooldown[str(guildid)][str(memberid)]
            Configuration.set_persistent_var("join_cooldown", self.join_cooldown)

        for guild in self.bot.guilds:
            # report number of mutes to metrics server
            m.bot_welcome_mute.labels(guild_id=guild.id).set(len(self.join_cooldown[str(guild.id)]))

            # set verification periodically since channel setting can be changed in another cog
            self.set_verification_mode(guild)

            if self.discord_verification_flow and not self.join_cooldown[str(guild.id)]:
                # verification flow in effect, and nobody left to unmute.
                continue

            if not self.join_cooldown or not self.join_cooldown[str(guild.id)]:
                continue

            mute_role = guild.get_role(Configuration.get_var("muted_role"))
            my_mutes = copy.deepcopy(self.join_cooldown)
            for user_id, join_time in my_mutes[str(guild.id)].items():
                try:
                    member = guild.get_member(int(user_id))
                    if member is None:
                        # user left server.
                        remove_member_from_cooldown(guild.id, user_id)
                        continue

                    user_age = now - member.created_at.timestamp()
                    elapsed = int(now - join_time)
                    cooldown_time = 60 * self.mute_minutes_old_account  # 10 minutes default
                    if user_age < 60 * 60 * 24:  # 1 day
                        cooldown_time = 60 * self.mute_minutes_new_account  # 20 minutes default for new users

                    if elapsed > cooldown_time:
                        # member has waited long enough
                        if mute_role in member.roles:
                            await member.remove_roles(mute_role)
                        remove_member_from_cooldown(guild.id, user_id)

                except Exception as e:
                    # error with member. not sure why. log it and remove from cooldown to prevent repeats
                    remove_member_from_cooldown(guild.id, user_id)
                    await Utils.handle_exception(f"Failed to unmute new member {user_id} in guild {guild.id}",
                                                 self.bot, e)
                    log_channel = self.bot.get_config_channel(guild.id, Utils.log_channel)
                    if log_channel is not None:
                        await log_channel.send(f"Failed to unmute <@{user_id}>. Maybe someone should look into that?")
                    continue

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
        del self.join_cooldown[str(guild.id)]

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
                if self.mute_new_members:
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
        await ctx.send(Lang.get_locale_string('welcome/help', ctx))

    @welcome.command(aliases=['configmute', 'muteconfig', 'configure_mute', 'mute_configure', 'mute'])
    @commands.guild_only()
    async def mute_config(self, ctx, active: bool = None, mute_minutes_old: int = 10, mute_minutes_new: int = 20):
        """
        Mute settings for new members

        active: mute on or off
        mute_minutes_old: how long (minutes) to mute established accounts
        mute_minutes_new: how long (minutes) to mute accounts < 1 day old
        """
        self.set_verification_mode(ctx.guild)
        if self.discord_verification_flow:
            # discord verification flow precludes new-member muting
            await ctx.send("""
            Discord verification flow is in effect. Mute is configured in discord moderation settings.
            To enable skybot muting, unset entry_channel: `!channel_config set entry_channel 0`
            """)
            return

        if active is not None:
            self.mute_new_members = active
            self.mute_minutes_old_account = mute_minutes_old
            self.mute_minutes_new_account = mute_minutes_new
            Configuration.set_persistent_var(f"{ctx.guild.id}_mute_new_members", active)
            Configuration.set_persistent_var(f"{ctx.guild.id}_mute_minutes_old_account", mute_minutes_old)
            Configuration.set_persistent_var(f"{ctx.guild.id}_mute_minutes_new_account", mute_minutes_new)

        status = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("welcome/mute_settings_title", ctx, server_name=ctx.guild.name))

        status.add_field(name="Mute new members",
                         value=f"**{'ON' if self.mute_new_members else 'OFF'}**",
                         inline=False)
        status.add_field(name="Mute duration",
                         value=f"{self.mute_minutes_old_account} minutes",
                         inline=False)
        status.add_field(name="New account mute duration\n(< 1 day old) ",
                         value=f"{self.mute_minutes_new_account} minutes",
                         inline=False)
        await ctx.send(embed=status)

    @welcome.command(aliases=["list", "muted"])
    @commands.guild_only()
    async def list_muted(self, ctx):
        muted_role = ctx.guild.get_role(Configuration.get_var("muted_role"))
        cooling_down = []
        untracked_mute = []
        on_cooldown_not_muted = []
        for member in ctx.guild.members:
            if member.id in self.join_cooldown[ctx.guild.id]:
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
        if cooling_down:
            msg = '\n'.join(cooling_down)
            await ctx.send(f"**Members who are muted after recently joining:**\n{msg}")
        if untracked_mute:
            msg = '\n'.join(untracked_mute)
            await ctx.send(f"**Other members who are muted:**\n{msg}")
        if on_cooldown_not_muted:
            msg = '\n'.join(on_cooldown_not_muted)
            await ctx.send(f"**Members on the cooldown list WITHOUT mute**\n{msg}")
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

    @welcome.command(aliases=["nonmember", "shadows", "shadow"])
    @commands.guild_only()
    async def ping_unverified(self, ctx):
        guild = self.bot.get_guild(Configuration.get_var("guild_id"))
        try:
            nonmember_role = guild.get_role(Configuration.get_var("nonmember_role"))
            welcome_channel = self.bot.get_config_channel(guild.id, Utils.welcome_channel)
            rules_channel = self.bot.get_config_channel(guild.id, Utils.rules_channel)

            if welcome_channel and rules_channel:
                txt = Lang.get_locale_string("welcome/welcome_msg", ctx,
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
    async def on_member_join(self, member):
        self.bot.loop.create_task(self.mute_new_member(member))

        if self.discord_verification_flow:
            # do not welcome new members when using discord verification
            # set entry_channel to use discord verification
            return

        # TODO: check for rules reaction here for the case of returning member?
        #  remove it, *or* automatically reinstate member role

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
        if not self.mute_new_members:
            return

        # give other bots a chance to perform other actions first (like mute)
        await asyncio.sleep(5)
        # refresh member for up-to-date roles
        member = member.guild.get_member(member.id)

        mute_role = member.guild.get_role(Configuration.get_var("muted_role"))

        # only add mute if it hasn't already been added. This allows other mod-bots (gearbot) to mute re-joined members
        # and not interfere by allowing skybot to automatically un-muting later.
        if mute_role not in member.roles:
            self.join_cooldown[str(member.guild.id)][str(member.id)] = datetime.now().timestamp()
            Configuration.set_persistent_var("join_cooldown", self.join_cooldown)
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
            discrim = member.discriminator
            id = member.id
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

    @commands.command(aliases=['set_rules_message', 'setrulesid'])
    @commands.guild_only()
    async def set_rules_react_message_id(self, ctx, message_id: int):
        rules_channel = self.bot.get_config_channel(ctx.guild.id, Utils.rules_channel)
        try:
            rules = await rules_channel.fetch_message(message_id)
            Configuration.MASTER_CONFIG['rules_react_message_id'] = message_id
            Configuration.save()
            roles = Configuration.get_var("roles")
            await rules.clear_reactions()
            for emoji, role_id in roles.items():
                await rules.add_reaction(emoji)
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
        if message.author.bot or not hasattr(message.author, "guild") or message.author.guild_permissions.mute_members:
            return

        if await self.member_verify_action(message):
            # verification flow triggered. no further processing
            return

        member_role = message.guild.get_role(Configuration.get_var("member_role"))
        if member_role in message.author.roles:
            # message from regular member. no action for welcomer to take.
            return

        welcome_channel = self.bot.get_config_channel(message.guild.id, Utils.welcome_channel)
        rules_channel = self.bot.get_config_channel(message.guild.id, Utils.rules_channel)
        log_channel = self.bot.get_config_channel(message.guild.id, Utils.log_channel)
        if not welcome_channel or not rules_channel or message.channel.id != welcome_channel.id:
            # ignore when channels not configured
            # Only act on messages in welcome channel from here on
            return

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
