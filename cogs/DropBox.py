import asyncio
import io
from datetime import datetime

import discord
from discord import Forbidden, Embed, NotFound, HTTPException
from discord.ext import commands, tasks

from cogs.BaseCog import BaseCog
from utils import Lang, Questions, Utils, Logging
from utils.Database import DropboxChannel


class DropBox(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self.dropboxes = dict()
        self.responses = dict()
        self.drop_messages = dict()
        self.delivery_in_progress = dict()
        self.delete_in_progress = dict()
        self.loaded = False
        self.clean_in_progress = False
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        Logging.info("starting DropBox")

        for guild in self.bot.guilds:
            # fetch dropbox channels per server
            self.init_guild(guild.id)
            for row in DropboxChannel.select().where(DropboxChannel.serverid == guild.id):
                self.dropboxes[guild.id][row.sourcechannelid] = row
        self.loaded = True

        self.deliver_to_channel.start()
        # TODO: find out what the condition is we need to wait for instead of just sleep
        # await asyncio.sleep(20)
        self.clean_channels.start()

    def init_guild(self, guild_id):
        self.dropboxes[guild_id] = dict()
        self.drop_messages[guild_id] = dict()
        self.delivery_in_progress[guild_id] = dict()
        self.delete_in_progress[guild_id] = dict()

    def cog_unload(self):
        self.deliver_to_channel.cancel()
        self.clean_channels.cancel()

    async def cog_check(self, ctx):
        if not hasattr(ctx.author, 'guild'):
            return False
        return ctx.author.guild_permissions.ban_members

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.dropboxes[guild.id]
        del self.drop_messages[guild.id]
        del self.delivery_in_progress[guild.id]
        del self.delete_in_progress[guild.id]

    @tasks.loop(seconds=1.0)
    async def deliver_to_channel(self):
        for guild_id, guild_queue in self.drop_messages.items():
            for channel_id, message_queue in guild_queue.items():
                try:
                    # get dropbox channel
                    drop_channel = self.bot.get_channel(self.dropboxes[guild_id][channel_id].targetchannelid)
                    working_queue = dict(message_queue)
                    for message_id, message in working_queue.items():
                        if channel_id not in self.delivery_in_progress[guild_id]:
                            self.delivery_in_progress[guild_id][channel_id] = set()
                        if message_id not in self.delivery_in_progress[guild_id][channel_id]:
                            self.delivery_in_progress[guild_id][channel_id].add(message_id)
                            self.bot.loop.create_task(self.drop_message_impl(message, drop_channel))
                except Exception as e:
                    pass

    async def drop_message_impl(self, source_message, drop_channel):
        guild_id = source_message.channel.guild.id
        source_channel_id = source_message.channel.id
        source_message_id = source_message.id
        embed = Embed(
            timestamp=source_message.created_at,
            color=0x663399)
        embed.set_author(name=f"{source_message.author} ({source_message.author.id})",
                         icon_url=source_message.author.avatar_url_as(size=32))
        embed.add_field(name="Author link", value=source_message.author.mention)
        ctx = await self.bot.get_context(source_message)

        try:
            # send embed and message to dropbox channel
            for attachment in source_message.attachments:
                try:
                    buffer = io.BytesIO()
                    await attachment.save(buffer)
                    await drop_channel.send(file=discord.File(buffer, attachment.filename))
                except Exception as attach_e:
                    await drop_channel.send(
                        f"Attachment from {source_message.author.mention} failed. Censored or deleted by member?")

            await drop_channel.send(embed=embed, content=source_message.content)

            # TODO: try/ignore: add reaction for "claim" "flag" "followup" "delete"
            msg = Lang.get_locale_string('dropbox/msg_delivered', ctx, author=source_message.author.mention)
            await ctx.send(msg)
        except Exception as e:
            msg = Lang.get_locale_string('dropbox/msg_not_delivered', ctx, author=source_message.author.mention)
            await ctx.send(msg)
            await Logging.guild_log(ctx, "broken dropbox...? Call alex, I guess")
            await Utils.handle_exception("dropbox delivery failure", self.bot, e)

        try:
            await source_message.delete()
            del self.drop_messages[guild_id][source_channel_id][source_message_id]
            set(self.delivery_in_progress[guild_id][source_channel_id]).remove(source_message_id)
        except discord.errors.NotFound as e:
            # ignore missing message
            pass

    @tasks.loop(seconds=3.0)
    async def clean_channels(self):
        if self.clean_in_progress:
            return

        self.clean_in_progress = True

        for guild in self.bot.guilds:
            for channel_id, drop in dict(self.dropboxes[guild.id]).items():
                if drop.deletedelayms == 0:
                    # do not clear from dropbox channels with no delay set.
                    continue

                channel = None
                # Look for channel history. Try 10 times to fetch channel history
                # this API call fails on startup because connection is not made yet.
                now = datetime.utcnow()
                channel = self.bot.get_channel(channel_id)
                if channel_id not in self.delete_in_progress[guild.id]:
                    self.delete_in_progress[guild.id][channel_id] = set()

                try:
                    async for message in channel.history(limit=20):
                        # check if message is queued for delivery
                        if (channel_id in self.drop_messages[guild.id]) and\
                                (message.id in self.drop_messages[guild.id][channel_id]):
                            # don't delete messages that are queued
                            continue
                        my_member = guild.get_member(message.author.id)
                        if my_member is None:
                            continue
                        is_mod = my_member.guild_permissions.ban_members
                        age = (now-message.created_at).seconds
                        expired = age > drop.deletedelayms / 1000
                        queued_for_delete = message.id in self.delete_in_progress[guild.id][channel_id]
                        # periodically clear out expired messages sent by bot and non-mod
                        if expired and not queued_for_delete and (message.author.bot or not is_mod):
                            self.delete_in_progress[guild.id][channel_id].add(message.id)
                            self.bot.loop.create_task(self.clean_message(message))
                        else:
                            pass
                except Exception as e:
                    await Utils.handle_exception('dropbox clean failure', self.bot, e)
                    # ignore. will try again soon?
        self.clean_in_progress = False

    async def clean_message(self, message):
        try:
            await message.delete()
            self.delete_in_progress[message.channel.guild.id][message.channel.id].remove(message.id)
        except (NotFound, HTTPException, Forbidden) as e:
            # ignore delete failure. we'll try again next time
            await Utils.handle_exception('dropbox clean_message failure', self.bot, e)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.dropboxes[guild.id]
        del self.drop_messages[guild.id]
        for row in DropboxChannel.select().where(DropboxChannel.serverid == guild.id):
            row.delete_instance()

    @commands.group(name="dropbox", invoke_without_command=True)
    @commands.guild_only()
    async def dropbox(self, ctx):
        # list dropbox channels
        embed = Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("dropbox/list", ctx, server_name=ctx.guild.name))
        for source, dropbox in self.dropboxes[ctx.guild.id].items():
            source_channel = self.bot.get_channel(source)
            target_channel = self.bot.get_channel(dropbox.targetchannelid)
            embed.add_field(name=f"From",
                            value=Utils.get_channel_description(self.bot, source_channel.id),
                            inline=True)
            embed.add_field(name=f"To",
                            value=Utils.get_channel_description(self.bot, target_channel.id),
                            inline=True)
            embed.add_field(name=f"Delete After",
                            value=Utils.to_pretty_time(dropbox.deletedelayms/1000) or "off",
                            inline=True)
            embed.add_field(name="__                                             __",
                            value="__                                             __",
                            inline=False)
        if len(self.dropboxes[ctx.guild.id]) == 0:
            embed.add_field(name="Not Set", value="Add dropboxes using `dropbox add` command")
        await ctx.send(embed=embed)

    @dropbox.command()
    @commands.guild_only()
    async def add(self, ctx, sourceid: int, targetid: int):
        # validate channel ids
        source_channel = self.bot.get_channel(sourceid)
        target_channel = self.bot.get_channel(targetid)
        if not source_channel:
            await ctx.send(Lang.get_locale_string('dropbox/channel_not_found', ctx, channel_id=sourceid))
        if not target_channel:
            await ctx.send(Lang.get_locale_string('dropbox/channel_not_found', ctx, channel_id=targetid))
        if not source_channel or not target_channel:
            # valid source and target channels are required
            return

        # initialize to None for the case of adding a new entry
        update_entry = None

        # channel descriptions
        source_description = Utils.get_channel_description(self.bot, sourceid)
        new_target_description = Utils.get_channel_description(self.bot, targetid)
        old_target_description = ""

        def update(choice):
            nonlocal update_entry
            update_entry = choice

        if sourceid in self.dropboxes[ctx.guild.id]:
            # existing source channel. ask user to confirm
            old_target_description = Utils.get_channel_description(
                self.bot,
                self.dropboxes[ctx.guild.id][sourceid].targetchannelid)
            await Questions.ask(
                self.bot,
                ctx.channel,
                ctx.author,
                Lang.get_locale_string('dropbox/override_confirmation',
                                       ctx,
                                       source=source_description,
                                       old_target=old_target_description,
                                       new_target=new_target_description),
                [
                    Questions.Option('YES', handler=lambda: update(True)),
                    Questions.Option('NO', handler=lambda: update(False))
                ], delete_after=True, locale=ctx)

        if update_entry is False:
            # user chose not to update
            await ctx.send(Lang.get_locale_string('dropbox/not_updating', ctx))
            return

        if update_entry:
            # user chose to update
            msg = Lang.get_locale_string('dropbox/updated',
                                         ctx,
                                         source=source_description,
                                         old_target=old_target_description,
                                         new_target=new_target_description)
        else:
            # no existing source. adding a new dropbox
            msg = Lang.get_locale_string('dropbox/added',
                                         ctx,
                                         source=source_description,
                                         target=new_target_description)

        # update local mapping and save to db
        db_row = DropboxChannel.get_or_create(serverid=ctx.guild.id, sourcechannelid=sourceid)[0]
        db_row.targetchannelid = targetid
        db_row.save()
        self.dropboxes[ctx.guild.id][sourceid] = db_row

        # message success to user
        await ctx.send(msg)

    @dropbox.command()
    @commands.guild_only()
    async def remove(self, ctx, sourceid: int):
        source_description = Utils.get_channel_description(self.bot, sourceid)
        if sourceid not in self.dropboxes[ctx.guild.id]:
            await ctx.send(Lang.get_locale_string('dropbox/not_removed', ctx, source=source_description))
            return

        try:
            DropboxChannel.get(serverid=ctx.guild.id,
                               sourcechannelid=sourceid).delete_instance()
            del self.dropboxes[ctx.guild.id][sourceid]
        except Exception as e:
            await Utils.handle_exception('dropbox delete failure', self.bot, e)
            raise e
        await ctx.send(Lang.get_locale_string('dropbox/removed', ctx, source=source_description))

    @dropbox.command(aliases=['delay', 'delete_delay'])
    @commands.guild_only()
    async def set_delay(self, ctx, channel: discord.TextChannel, delay: int):
        """
        Set the lifespan for response messages in the channel

        Also applies to any non-mod messages, so the delay time must be greater than the initial wait for message drops.
        delay: Time until responses expire (milliseconds)
        """
        if channel.id in self.dropboxes[ctx.guild.id]:
            drop = self.dropboxes[ctx.guild.id][channel.id]
            drop.deletedelayms = delay
            drop.save()
            t = Utils.to_pretty_time(delay/1000)
            await ctx.send(f'Confirmation messages in dropbox channel {channel.mention} will be deleted after {t}')
        else:
            await ctx.send(f'Failed to set dropbox delete delay time in {channel.mention}')

    @commands.Cog.listener()
    async def on_message(self, message: discord.message):
        try:
            guild_id = message.channel.guild.id
            message_not_in_guild = not hasattr(message.channel, "guild") or message.channel.guild is None
            author_not_in_guild = not hasattr(message.author, "guild")
            channel_not_in_dropboxes = message.channel.id not in self.dropboxes[guild_id]
            is_mod = message.author.guild_permissions.ban_members
        except Exception as e:
            return

        if message.author.bot or message_not_in_guild or author_not_in_guild or \
                channel_not_in_dropboxes or is_mod:
            # check for dropbox matching channel id
            # ignore bots and mods/admins
            return

        # queue this message id for delivery/deletion
        if message.channel.id not in self.drop_messages[guild_id]:
            self.drop_messages[guild_id][message.channel.id] = dict()
        self.drop_messages[guild_id][message.channel.id][message.id] = message


def setup(bot):
    bot.add_cog(DropBox(bot))
