from datetime import datetime

from utils.Database import ReactWatch

import copy
import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Utils, Configuration, Lang


muted_roles = {
    621746949485232154: 624294429838147634,
    575762611111592007: 600490107472052244
}
# TODO: move emoji to db, add commands for adding/removing
# TODO: option for mute if mute role is set. config command to set/unset mute role


class ReactMonitor(BaseCog):

    def __init__(self, bot):
        self.react_watch_servers = set()
        self.recent_reactions = dict()
        self.react_removers = dict()
        self.ban_lists = dict()
        self.watch_lists = dict()
        # TODO: make this persistent key guild-specific
        self.min_react_lifespan = Configuration.get_persistent_var("min_react_lifespan", 2)
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        for guild in self.bot.guilds:
            watch = ReactWatch.get_or_create(serverid=guild.id)[0]
            # track react add/remove per guild
            self.recent_reactions[guild.id] = dict()
            self.react_removers[guild.id] = dict()
            self.ban_lists[guild.id] = str(watch.banlist).split(" ")
            self.watch_lists[guild.id] = str(watch.watchlist).split(" ")
            # enable listening if set in db
            if watch.watchremoves:
                self.activate_react_watch(guild.id)

    def activate_react_watch(self, guild_id):
        watch = ReactWatch.get(serverid=guild_id)
        watch.watchremoves = True
        watch.save()
        self.react_watch_servers.add(guild_id)

    def deactivate_react_watch(self, guild_id):
        watch = ReactWatch.get(serverid=guild_id)
        watch.watchremoves = False
        watch.save()
        self.react_watch_servers.remove(guild_id)

    async def is_user_event_ignored(self, event):
        server_is_listening = event.guild_id in self.react_watch_servers
        is_bot = event.user_id == self.bot.user.id
        is_owner = await self.bot.is_owner(self.bot.get_user(event.user_id))
        is_admin = event.user_id in Configuration.get_var("ADMINS", [])
        has_admin = event.user_id in Configuration.get_var("admin_roles", [])
        if (event.event_type == "REACTION_REMOVE" and not server_is_listening) or is_bot or is_owner or is_admin or has_admin:
            return True
        return False

    def has_control(ctx):
        return ctx.author.guild_permissions.mute_members

    @commands.group(name="reactmonitor", aliases=['reactmon'], invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    @commands.check(has_control)
    async def react_monitor(self, ctx: commands.Context):
        watch = ReactWatch.get(serverid=ctx.guild.id)
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_string("react_monitor/info_title", server_name=ctx.guild.name))

        embed.add_field(name="Monitor React Removal", value="Yes" if watch.watchremoves else "No")

        if watch.watchremoves:
            embed.add_field(name="Reaction minimum lifespan", value=str(self.min_react_lifespan))

        if ctx.guild.id in self.ban_lists and self.ban_lists[ctx.guild.id] and ' '.join(self.ban_lists[ctx.guild.id]):
            # banned emoji list is not empty set
            embed.add_field(name="Banned Emojis", value=' '.join(self.ban_lists[ctx.guild.id]), inline=False)

        if ctx.guild.id in self.watch_lists and self.watch_lists[ctx.guild.id] and ' '.join(self.watch_lists[ctx.guild.id]):
            # watched emoji list is not empty set
            embed.add_field(name="Watched Emojis", value=' '.join(self.watch_lists[ctx.guild.id]), inline=False)

        await ctx.send(embed=embed)

    @react_monitor.command(aliases=["new"])
    @commands.guild_only()
    @commands.check(has_control)
    async def on(self, ctx: commands.Context):
        self.activate_react_watch(ctx.guild.id)
        await ctx.send("I'm on the lookout for reaction spam!")

    @react_monitor.command(aliases=["del", "delete"])
    @commands.guild_only()
    @commands.check(has_control)
    async def off(self, ctx: commands.Context):
        self.deactivate_react_watch(ctx.guild.id)
        await ctx.send("OK, I'll stop watching for reaction spams")

    @react_monitor.command(aliases=["time", "reacttime"])
    @commands.guild_only()
    @commands.check(has_control)
    async def react_time(self, ctx: commands.Context, react_time: float):
        self.min_react_lifespan = react_time
        # TODO: make this persistent key guild-specific
        Configuration.set_persistent_var("min_react_lifespan", react_time)
        await ctx.send(f"Reactions that are removed before {react_time} seconds have passed will be flagged")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        watch = ReactWatch.create(serverid=guild.id)
        # track react add/remove per guild
        self.recent_reactions[guild.id] = dict()
        self.react_removers[guild.id] = dict()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.recent_reactions[guild.id]
        del self.react_removers[guild.id]
        if guild.id in self.react_watch_servers:
            self.deactivate_react_watch(guild.id)
        ReactWatch.get(ReactWatch.serverid == guild.id).delete_instance()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        if await self.is_user_event_ignored(event):
            return

        emoji_used = str(event.emoji)
        member = event.member
        guild = self.bot.get_guild(event.guild_id)
        channel = self.bot.get_channel(event.channel_id)
        message = await channel.fetch_message(event.message_id)
        muted_role = guild.get_role(muted_roles[guild.id])

        # Add message id/reaction/timestamp to dict for tracking fast removal of reactions
        now = datetime.now().timestamp()
        self.recent_reactions[guild.id][str(now)] = {"message_id": message.id, "user_id": event.user_id}

        log_channel = self.bot.get_config_channel(message.guild.id, Utils.log_channel)
        rules_channel = self.bot.get_config_channel(guild.id, Utils.rules_channel)

        if channel != rules_channel and muted_role in member.roles:
            await message.remove_reaction(emoji_used, member)
            if log_channel:
                await log_channel.send(f"Muted member {member.nick or member.name}#{member.discriminator} "
                                       f"({member.id}) tried to react with {emoji_used} in #{channel.name}.\n"
                                       f"{message.jump_url}")
            return

        if emoji_used in self.ban_lists[event.guild_id]:
            await message.clear_reaction(emoji_used)
            await member.add_roles(muted_role)
            # ping log channel with detail
            if log_channel:
                await log_channel.send(f"I muted {member.mention} for using blacklisted emoji "
                                       f"{emoji_used} in #{channel.name}.\n"
                                       f"{message.jump_url}")
        if emoji_used in self.watch_lists[event.guild_id]:
            # ping log channel with detail
            if log_channel:
                await log_channel.send(f"{member.mention} used watched emoji {emoji_used} in #{channel.name}.\n"
                                       f"{message.jump_url}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, event):
        now = datetime.now().timestamp()
        # TODO: Evaluate - count react removal and auto-mute for hitting threshold in given time?
        # Add user_id to dict of recent reaction removers with timestamp
        # self.react_removers[event.guild_id][now] = event.user_id

        # clear old events out of the reaction storage
        if self.recent_reactions[event.guild_id]:
            my_reacts = copy.deepcopy(self.recent_reactions[event.guild_id])
            min_key = min(my_reacts.keys())
            t = float(min_key) + self.min_react_lifespan
            while t < now:
                my_reacts.pop(min_key, None)
                if my_reacts:
                    min_key = min(my_reacts.keys())
                    t = float(min_key) + self.min_react_lifespan
                else:
                    break
            self.recent_reactions[event.guild_id] = copy.deepcopy(my_reacts)

        if await self.is_user_event_ignored(event):
            return

        # purge old reaction adds. check recent ones if they match remove event
        for t, info in self.recent_reactions[event.guild_id].items():
            is_message = info['message_id'] == event.message_id
            is_user = info['user_id'] == event.user_id
            if is_message and is_user:
                # This user is removing a reaction they adding within the warning time window
                guild = self.bot.get_guild(event.guild_id)
                member = guild.get_member(event.user_id)
                emoji_used = str(event.emoji)
                channel = self.bot.get_channel(event.channel_id)
                message = await channel.fetch_message(event.message_id)
                log_channel = self.bot.get_config_channel(guild.id, Utils.log_channel)
                # ping log channel with detail
                if log_channel:
                    await log_channel.send(f"{member.mention} quick-removed reaction {emoji_used} from a message "
                                           f"in {channel.mention}\n"
                                           f"{message.jump_url}")


def setup(bot):
    bot.add_cog(ReactMonitor(bot))
