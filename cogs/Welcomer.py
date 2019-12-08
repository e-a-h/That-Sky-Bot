from datetime import date, datetime

from discord.ext import commands
from cogs.BaseCog import BaseCog
from utils import Configuration, Logging, Utils


class Welcomer(BaseCog):

    async def cog_check(self, ctx):
        return ctx.author.guild_permissions.ban_members

    async def is_member_verified(self, member):
        try:
            guild = self.bot.get_guild(Configuration.get_var("guild_id"))
            if member not in guild.members:
                return True  # non-members are "verified" so we don't try to interact with them
            member_role = guild.get_role(Configuration.get_var("member_role"))
            nonmember_role = guild.get_role(Configuration.get_var("nonmember_role"))
            if member_role not in member.roles:
                await member.add_roles(nonmember_role)
                return False
            return True
        except Exception as ex:
            return True  # exceptions are "verified" so we don't try to interact with them *again*

    async def send_welcome(self, member):
        guild = self.bot.get_guild(Configuration.get_var("guild_id"))
        if member.guild.id != guild.id or await self.is_member_verified(member):
            return False

        try:
            txt = Configuration.get_var("welcome_msg")
            welcome_channel = self.bot.get_channel(Configuration.get_var('welcome_channel'))
            txt = txt.format(user=member.mention)
            if welcome_channel is not None:
                await welcome_channel.send(txt)
                return True
        except Exception as ex:
            Logging.info(f"failed to welcome {member.id}")
            Logging.error(ex)
            raise ex
        return False

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = self.bot.get_guild(Configuration.get_var("guild_id"))
        if member.guild.id != guild.id:
            return

        nonmember_role = guild.get_role(Configuration.get_var("nonmember_role"))
        await member.add_roles(nonmember_role)
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

    @commands.group(name="welcome", invoke_without_command=True)
    @commands.guild_only()
    async def welcome(self, ctx):
        await ctx.send("welcome (recent) [hours]")

    @welcome.command()
    @commands.guild_only()
    async def recent(self, ctx, time_delta: int = 24, ping: bool = False):
        """
        Manually welcome all members who have joined within a certain number of hours
        :param ctx:
        :param time_delta: number of hours within which members have joined
        :param ping: send welcome to members in welcome channel
        :return:
        """
        await ctx.send(f"fetching members who joined in the last {time_delta} hours...")
        recent = await self.fetch_recent(time_delta)

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
                if not await self.is_member_verified(member[0]):
                    pending_welcome.append(member[1])
                continue
            try:
                sent = await self.send_welcome(member[0])
            except Exception as ex:
                sent = False
            if sent:
                welcomed.append(member[1])
            else:
                failed_welcome.append(member[1])

        welcomed_lists = list(Utils.split_list(welcomed, 50))
        failed_lists = list(Utils.split_list(not_welcomed, 50))
        pending_welcome_lists = list(Utils.split_list(pending_welcome, 50))

        for members in welcomed_lists:
            await ctx.send("**Welcomed these members:**\n " + '\n '.join(members))
        for members in failed_lists:
            await ctx.send("**Failed to welcome these members:**\n " + '\n '.join(members))
        for members in pending_welcome_lists:
            await ctx.send(f"**These members joined in the last {time_delta} hours and need to be welcomed:**" + "\n " + '\n '.join(members))

        await ctx.send(f"**Ignored {len(verified)} members who already have a verified role**")
        await ctx.send(f"**There are {len(too_old)} unverified members who joined too long ago**")

    async def fetch_recent(self, time_delta: int = 24):
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
                continue
            # guild members, non-bot:
            nick = ""
            if member.nick:
                nick = f'*"{member.nick}"*'
            member_description = f"{member.name}#{member.discriminator} ({member.id}) {nick} " \
                                 f"- joined {int((now-member.joined_at.timestamp())/60/60)} hours ago"

            if await self.is_member_verified(member):
                verified_members.append([member, member_description])

            if member.joined_at.timestamp() > then:
                unverified_members.append([member, member_description])
            else:
                too_old_members.append([member, member_description])
        return {
            "unverified": unverified_members,
            "verified": verified_members,
            "too_old": too_old_members
        }

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
