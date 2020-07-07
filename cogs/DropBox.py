import asyncio
import io
from datetime import datetime

import discord
from discord import Embed
from discord.ext import commands, tasks

from cogs.BaseCog import BaseCog
from utils import Lang, Questions, Utils, Logging
from utils.Database import DropboxChannel


class DropBox(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self.dropboxes = dict()
        self.responses = dict()
        self.loaded = False
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        await self.bot.wait_until_ready()
        Logging.info("starting DropBox")

        for guild in self.bot.guilds:
            # fetch dropbox channels per server
            self.dropboxes[guild.id] = dict()
            for row in DropboxChannel.select().where(DropboxChannel.serverid == guild.id):
                self.dropboxes[guild.id][row.sourcechannelid] = row
        self.loaded = True
        self.clean_channels.start()

    def cog_unload(self):
        self.clean_channels.cancel()

    async def cog_check(self, ctx):
        if not hasattr(ctx.author, 'guild'):
            return False
        return ctx.author.guild_permissions.ban_members

    @tasks.loop(seconds=1.0)
    async def clean_channels(self):
        for guild in self.bot.guilds:
            for channel_id, drop in dict(self.dropboxes[guild.id]).items():
                channel = None
                while not channel:
                    # Keep looking for channel history until we have it.
                    # this API call fails on startup because connection is not made yet.
                    # TODO: properly wait for connection to be initialized
                    Logging.info(f"dropbox channel {channel_id}")

                    try:
                        if drop.deletedelayms == 0:
                            Logging.info(f"no clean for {channel_id}")
                            # do not clear from dropbox channels with no delay set.
                            break
                        now = datetime.utcnow()
                        channel = self.bot.get_channel(channel_id)
                        async for message in channel.history(limit=20):
                            age = (now-message.created_at).seconds
                            expired = age > drop.deletedelayms / 1000
                            # periodically clear out expired messages sent by bot and non-mod
                            if expired and (message.author.bot or not message.author.guild_permissions.ban_members):
                                try:
                                    await message.delete()
                                except Exception as e:
                                    # ignore delete failure. we'll try again next time
                                    pass
                    except Exception as e:
                        await Utils.handle_exception('Dropox clean_channels exception', self.bot, e)
                        await asyncio.sleep(30)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.dropboxes[guild.id] = dict()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.dropboxes[guild.id]
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
        not_in_guild = not hasattr(message.channel, "guild") or message.channel.guild is None
        if not_in_guild or \
                message.channel.id not in self.dropboxes[message.channel.guild.id] or \
                not hasattr(message.author, "guild") or \
                message.author.guild_permissions.ban_members or \
                message.author.bot:
            # check for dropbox matching channel id
            # ignore bots and mods/admins
            return

        #  wait for other bots to act, then check if message deleted (censored)
        await asyncio.sleep(1)
        try:
            ctx = await self.bot.get_context(message)
            message = await ctx.channel.fetch_message(message.id)
        except (discord.NotFound, discord.HTTPException):
            # message was deleted. maybe by another bot
            # if delivery confirmation, message failure
            pass
        else:
            # message is still there, let's deliver to dropbox!
            # create embed with author description
            embed = Embed(
                timestamp=ctx.message.created_at,
                color=0x663399)
            embed.set_author(name=f"{ctx.author} ({ctx.author.id})", icon_url=ctx.author.avatar_url_as(size=32))
            embed.add_field(name="Author link", value=ctx.author.mention)
            try:
                # send embed and message to dropbox channel
                drop_channel = self.bot.get_channel(
                    self.dropboxes[message.channel.guild.id][message.channel.id].targetchannelid)

                for attachment in message.attachments:
                    buffer = io.BytesIO()
                    await attachment.save(buffer)
                    await drop_channel.send(file=discord.File(buffer, attachment.filename))
                await drop_channel.send(embed=embed, content=message.content)

                # TODO: try/ignore: add reaction for "claim" "flag" "followup" "delete"
                msg = Lang.get_locale_string('dropbox/msg_delivered', ctx, author=ctx.author.mention)
                await ctx.send(msg)
            except Exception as e:
                msg = Lang.get_locale_string('dropbox/msg_not_delivered', ctx, author=ctx.author.mention)
                await ctx.send(msg)
                await Utils.handle_exception("dropbox delivery failure", self.bot, e)

            await message.delete()


def setup(bot):
    bot.add_cog(DropBox(bot))
