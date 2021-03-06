from datetime import datetime

from utils.Database import ReactWatch, WatchedEmoji, Guild

import discord
from discord import NotFound, HTTPException
from discord.ext import commands, tasks

from cogs.BaseCog import BaseCog
from utils import Utils, Configuration, Lang, Logging


class ReactMonitor(BaseCog):

    def __init__(self, bot):
        self.react_watch_servers = set()
        self.recent_reactions = dict()
        self.react_removers = dict()
        self.react_adds = dict()
        self.emoji = dict()
        self.min_react_lifespan = 0.0
        self.mutes = dict()
        self.mute_duration = dict()
        self.guilds = dict()
        super().__init__(bot)
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        self.mutes = dict()
        for guild in self.bot.guilds:
            self.mutes[guild.id] = Configuration.get_persistent_var(f"react_mutes_{guild.id}", dict())
            self.init_guild(guild.id)
        self.check_reacts.start()

    def init_guild(self, guild_id):
        watch = ReactWatch.get_or_create(serverid=guild_id)[0]
        self.min_react_lifespan = Configuration.get_persistent_var(f"min_react_lifespan_{guild_id}", 0.5)
        self.mute_duration[guild_id] = watch.muteduration

        # track react add/remove per guild
        self.recent_reactions[guild_id] = dict()
        self.react_removers[guild_id] = dict()
        self.react_adds[guild_id] = dict()

        # list of emoji to watch
        self.emoji[guild_id] = dict()
        for e in watch.emoji:
            self.emoji[guild_id][e.emoji] = e

        # enable listening if set in db
        if watch.watchremoves:
            self.activate_react_watch(guild_id)

        self.guilds[guild_id] = Guild.get_or_create(serverid=guild_id)[0]

    def cog_unload(self):
        self.check_reacts.cancel()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        Configuration.del_persistent_var(f"min_react_lifespan_{guild.id}")
        del self.recent_reactions[guild.id]
        del self.react_removers[guild.id]
        del self.react_adds[guild.id]
        del self.emoji[guild.id]
        del self.guilds[guild.id]
        if guild.id in self.react_watch_servers:
            self.deactivate_react_watch(guild.id)
        watch = ReactWatch.get(ReactWatch.serverid == guild.id)
        for e in watch.emoji:
            e.delete_instance()
        watch.delete_instance()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        self.store_reaction_action(event)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, event):
        self.store_reaction_action(event)

    def activate_react_watch(self, guild_id):
        # store setting in db, and add to list of listening servers
        watch = ReactWatch.get(serverid=guild_id)
        watch.watchremoves = True
        watch.save()
        self.react_watch_servers.add(guild_id)

    def deactivate_react_watch(self, guild_id):
        # store setting in db, and remove from list of listening servers
        watch = ReactWatch.get(serverid=guild_id)
        watch.watchremoves = False
        watch.save()
        self.react_watch_servers.remove(guild_id)

    def is_user_event_ignored(self, event):
        ignored_channels = Configuration.get_var('channels')
        is_ignored_channel = event.channel_id in ignored_channels.values()
        guild = self.bot.get_guild(event.guild_id)
        if not guild:
            # Don't listen to DMs
            return True
        is_bot = event.user_id == self.bot.user.id
        member = guild.get_member(event.user_id)

        if member is None:
            return True  # ignore reaction events from departing members

        is_mod = member and member.guild_permissions.ban_members
        is_admin = event.user_id in Configuration.get_var("ADMINS", [])
        has_admin = False

        for role in member.roles:
            if role in Configuration.get_var("admin_roles", []):
                has_admin = True

        # ignore bot, ignore mod, ignore admin users and admin roles
        if is_bot or is_mod or is_admin or has_admin or is_ignored_channel:
            return True
        return False

    async def cog_check(self, ctx):
        if not hasattr(ctx.author, 'guild'):
            return False
        return ctx.author.guild_permissions.mute_members

    @tasks.loop(seconds=1.0)
    async def check_reacts(self):
        now = datetime.now().timestamp()
        for guild_id in self.recent_reactions:
            try:
                for user_id, mute_time in dict(self.mutes[guild_id]).items():
                    if float(mute_time) + float(self.mute_duration[guild_id]) < now:
                        try:
                            guild = self.bot.get_guild(guild_id)
                            guild_config = self.bot.get_config(guild_id)
                            if guild_config and guild_config.mutedrole:
                                mute_role = guild.get_role(guild_config.mutedrole)
                                member = guild.get_member(int(user_id))
                                if mute_role in member.roles:
                                    await member.remove_roles(mute_role)
                                del self.mutes[guild_id][user_id]
                        except Exception as e:
                            log_channel = self.bot.get_guild_log_channel(guild_id)
                            del self.mutes[guild_id][user_id]
                            await log_channel.send(f'Failed to unmute user ({user_id}) <@{user_id}>... did they leave the server?')
                            await Utils.handle_exception('react watch unmute failure', self.bot, e)
                rr = self.recent_reactions[guild_id]
                adds = {t: e for (t, e) in rr.items() if e.event_type == "REACTION_ADD"}

                # creat list of adds
                for t, e in adds.items():
                    self.react_adds[guild_id][t] = e
                # cull out expired ones
                for t, e in dict(self.react_adds[guild_id]).items():
                    if t + self.min_react_lifespan < now:
                        # add reaction is too far in the past. remove from the list
                        del self.react_adds[guild_id][t]

                # loop over a copy of recent_reactions so we can remove items
                for timestamp, event in dict(self.recent_reactions[guild_id]).items():
                    # remove this one from the list
                    del self.recent_reactions[guild_id][timestamp]

                    p = getattr(self, 'process_'+event.event_type.lower())
                    await p(timestamp, event)

            except Exception as ex:
                await Utils.handle_exception('react watch loop error...', self, ex)

    @commands.group(name="reactmonitor",
                    aliases=['reactmon', 'reactwatch', 'react', 'watcher'],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def react_monitor(self, ctx: commands.Context):
        """
        List the watched emoji and their settings
        """
        watch = ReactWatch.get(serverid=ctx.guild.id)
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=Utils.COLOR_LIME,
            title=Lang.get_locale_string("react_monitor/info_title", ctx, server_name=ctx.guild.name))

        embed.add_field(name="Monitor React Removal", value="Yes" if watch.watchremoves else "No")

        if watch.watchremoves:
            embed.add_field(name="Reaction minimum lifespan", value=f"{self.min_react_lifespan} seconds")

        embed.add_field(name="Mute duration", value=Utils.to_pretty_time(self.mute_duration[ctx.guild.id]))

        embed.add_field(name="__                                             __",
                        value="__                                             __",
                        inline=False)

        if ctx.guild.id in self.emoji:
            for key, emoji in self.emoji[ctx.guild.id].items():
                embed.add_field(
                    name=f"{emoji.emoji}",
                    value=self.describe_emoji_watch_settings(emoji),
                    inline=True)

        await ctx.send(embed=embed)

    @staticmethod
    def describe_emoji_watch_settings(emoji):
        flags = [f"__*{name}*__" for name in ['log', 'remove', 'mute'] if getattr(emoji, name)]
        val = ' | '.join(flags) if flags else '__*no action*__'
        return val

    @react_monitor.command(aliases=["new", "edit", "update"])
    @commands.guild_only()
    async def add(self, ctx: commands.Context, emoji, log: bool = True, remove: bool = False, mute: bool = False ):
        """
        Add an emoji to the reaction watchlist

        emoji: The emoji to add
        log: Boolean - Log use of this emoji
        remove: Boolean - Auto-remove when this emoji is used
        mute: Boolean - Auto-mute members who use this emoji
        """
        try:
            watch = ReactWatch.get(serverid=ctx.guild.id)
            new_emoji = WatchedEmoji.get_or_create(watcher=watch.id, emoji=emoji)[0]
            new_emoji.log = log
            new_emoji.remove = remove
            new_emoji.mute = mute
            new_emoji.save()
            self.emoji[ctx.guild.id][emoji] = new_emoji
        except Exception as e:
            raise e
        await ctx.send(f"`{emoji}` is now on the watch list with settings:\n"
                       f"{self.describe_emoji_watch_settings(self.emoji[ctx.guild.id][emoji])}")

    @react_monitor.command(aliases=["rem", "del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, emoji):
        """
        Remove an emoji from the watch list

        emoji: The emoji to remove
        """
        try:
            watch = ReactWatch.get(serverid=ctx.guild.id)
            WatchedEmoji.get(watcher=watch.id, emoji=emoji).delete_instance()
            del self.emoji[ctx.guild.id][emoji]
            await ctx.send(f"I removed `{emoji}` from the watch list")
        except Exception as e:
            await ctx.send(f"I couldn't find `{emoji}` on the emoji watch list, so I didn't remove it.")

    @react_monitor.command()
    @commands.guild_only()
    async def on(self, ctx: commands.Context):
        """
        Turn on monitor for spammy fast-removal of reactions
        """
        if ctx.guild.id in self.react_watch_servers:
            await ctx.send("React monitor is already on")
        else:
            self.activate_react_watch(ctx.guild.id)
            await ctx.send("I'm on the lookout for reaction spam!")

    @react_monitor.command()
    @commands.guild_only()
    async def off(self, ctx: commands.Context):
        """
        Turn off monitor for spammy fast-removal of reactions
        """
        if ctx.guild.id in self.react_watch_servers:
            self.deactivate_react_watch(ctx.guild.id)
            await ctx.send("OK, I'll stop watching for reaction spams")
        else:
            await ctx.send("React monitor is already off")

    @react_monitor.command(aliases=["time", "reacttime"])
    @commands.guild_only()
    async def react_time(self, ctx: commands.Context, react_time: float):
        """
        Set the threshold time below which reaction removal will trigger the react-watch

        react_time: time in seconds, floating point e.g. 0.25
        """
        self.min_react_lifespan = react_time
        Configuration.set_persistent_var(f"min_react_lifespan_{ctx.guild.id}", react_time)
        await ctx.send(f"Reactions that are removed before {react_time} seconds have passed will be flagged")

    @react_monitor.command(aliases=["mutetime", "mute"])
    @commands.guild_only()
    async def mute_time(self, ctx: commands.Context, mute_time: float):
        """
        Set the duration for mutes given when mute-enabled reacts are used

        mute_time: time in seconds, floating point e.g. 0.25
        """
        self.mute_duration[ctx.guild.id] = mute_time
        watch = ReactWatch.get_or_create(serverid=ctx.guild.id)[0]
        watch.muteduration = mute_time
        watch.save()
        t = Utils.to_pretty_time(mute_time)
        await ctx.send(f"Members will now be muted for {t} when they use restricted reacts")

    def store_reaction_action(self, event):
        if self.is_user_event_ignored(event):
            return

        # Add event to dict for tracking fast removal of reactions
        now = datetime.now().timestamp()
        guild = self.bot.get_guild(event.guild_id)
        self.recent_reactions[guild.id][now] = event

    async def process_reaction_add(self, timestamp, event):
        emoji_used = event.emoji
        member = event.member
        guild = self.bot.get_guild(event.guild_id)
        channel = self.bot.get_channel(event.channel_id)
        log_channel = self.bot.get_guild_log_channel(event.guild_id)

        # Act on log, remove, and mute:
        e_db = None
        if str(emoji_used) in self.emoji[event.guild_id]:
            e_db = self.emoji[event.guild_id][str(emoji_used)]
            if not e_db.log and not e_db.remove and not e_db.mute:
                # No actions to take. Stop processing
                return

        if not e_db:
            return

        # check mute/warn list for reaction_add - log to channel
        # for reaction_add, remove if threshold for quick-remove is passed
        try:
            # message fetch is API call. Only do it if needed
            message = await channel.fetch_message(event.message_id)
        except (NotFound, HTTPException) as e:
            # Can't track reactions on a message I can't find
            # Happens for deleted messages. Safe to ignore.
            # await Utils.handle_exception(f"Failed to get message {channel.id}/{event.message_id}", self, e)
            return

        log_msg = f"{Utils.get_member_log_name(member)} used emoji "\
                  f"[ {emoji_used} ] in #{channel.name}.\n"\
                  f"{message.jump_url}"

        if e_db.remove:
            await message.clear_reaction(emoji_used)
            log_msg = f"{log_msg}\n--- I **removed** the reaction"

        if e_db.mute:
            guild_config = self.bot.get_config(guild.id)
            if guild_config and guild_config.mutedrole:
                try:
                    mute_role = guild.get_role(guild_config.mutedrole)
                    await member.add_roles(mute_role)
                    self.mutes[guild.id][str(member.id)] = timestamp
                    Configuration.set_persistent_var(f"react_mutes_{guild.id}", self.mutes[guild.id])
                    log_msg = f"{log_msg}\n--- I **muted** them"
                except Exception as e:
                    await Utils.handle_exception("reactmon failed to mute member", self.bot, e)
            else:
                ctx = await self.bot.get_context(message)
                await Logging.guild_log(ctx, "**I can't mute for reacts because `!guildconfig` mute role is not set.")

        if (e_db.log or e_db.remove or e_db.mute) and log_channel:
            await log_channel.send(log_msg)

    async def process_reaction_remove(self, timestamp, event):
        # TODO: Evaluate - count react removal and auto-mute for hitting threshold in given time?
        #  i.e. track react-remove-count per user over time. if count > x: mute/warn

        # Add user_id to dict of recent reaction removers with timestamp
        # now = datetime.now().timestamp()
        # self.react_removers[event.guild_id][event.user_id] = now

        # listening setting only apples to quick-remove
        server_is_listening = event.guild_id in self.react_watch_servers
        if not server_is_listening or self.is_user_event_ignored(event):
            return

        # check recent reacts to see if they match the remove event
        for t, add_event in self.react_adds[event.guild_id].items():
            # Criteria for skipping an event in the list
            not_message = add_event.message_id != event.message_id
            not_user = add_event.user_id != event.user_id

            age = timestamp - t
            expired = 0 > age > self.min_react_lifespan
            if expired or not_message or not_user:
                # message id and user id must match remove event, and must not be expired
                continue

            # This user added a reaction that was removed within the warning time window
            guild = self.bot.get_guild(event.guild_id)
            member = guild.get_member(event.user_id)
            emoji_used = str(event.emoji)
            channel = self.bot.get_channel(event.channel_id)
            log_channel = self.bot.get_guild_log_channel(guild.id)
            # ping log channel with detail
            if log_channel:
                content = f"{Utils.get_member_log_name(member)} " \
                          f"quick-removed [ {emoji_used} ] react from a message in {channel.mention}"
                try:
                    message = await channel.fetch_message(event.message_id)
                    content = f"{content}\n{message.jump_url}"
                except (NotFound, HTTPException) as e:
                    pass
                await log_channel.send(content)


def setup(bot):
    bot.add_cog(ReactMonitor(bot))
