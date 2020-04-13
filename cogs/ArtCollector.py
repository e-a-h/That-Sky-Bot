import asyncio
import io
import mimetypes
import re
import time
from asyncio import CancelledError
from datetime import datetime

import discord
from discord import NotFound, Forbidden, Embed, HTTPException
from discord.ext import commands

from utils import Lang, Utils, Emoji, Configuration, Questions
from utils.Database import ArtChannel

from cogs.BaseCog import BaseCog
from utils.Utils import CHANNEL_ID_MATCHER


class ArtCollector(BaseCog):

    no_tag = "no_tag"
    listen_tag = "listen"

    art = "art"
    title = "title"
    description = "description"
    submit = "submit"
    cancel = "cancel"

    async def cog_check(self, ctx):
        return ctx.author.guild_permissions.ban_members

    def __init__(self, bot):
        super().__init__(bot)
        self.channels = dict()
        self.in_progress = dict()
        self.collection_channels = dict()
        self.art_messages = dict()
        self.ro_art_channels = dict()

        bot.loop.create_task(self.startup_cleanup())

    async def shutdown(self):
        for guild_id, channel in self.ro_art_channels.items():
            message = await channel.send(Lang.get_string("art/shutdown_message"))
            Configuration.set_persistent_var(f"art_shutdown_{guild_id}", message.id)

    async def startup_cleanup(self):
        await asyncio.sleep(2)
        for guild in self.bot.guilds:
            channel = self.bot.get_config_channel(guild.id, Utils.ro_art_channel)
            self.ro_art_channels[guild.id] = channel
            if channel is None:
                Utils.Logging.error(f"""
                ArtCollector read-only channel in guild "{guild.name}" is not set.
                Use `!channel_config set 'ro_art_channel', [id]` in that guild to initialize""")

            # Load channels
            await self.load_channels(guild)

        # clear shutdown messages and place trigger message in R/O art channel
        for guild_id, channel in self.ro_art_channels.items():
            if channel is not None:
                tracker = f"art_shutdown_{guild_id}"
                shutdown_id = Configuration.get_persistent_var(tracker)
                if shutdown_id != 0 and shutdown_id is not None:
                    message = await channel.fetch_message(shutdown_id)
                    if message is not None:
                        await message.delete()
                    Configuration.set_persistent_var(tracker, 0)
                await self.send_ro_art_info(channel)

    async def send_ro_art_info(self, channel):
        guild_id = channel.guild.id
        if channel is None or guild_id == 0:
            return

        info_msg_id = self.get_ro_art_info_message_id(guild_id)

        if info_msg_id is not None:
            try:
                message = await channel.fetch_message(info_msg_id)
            except NotFound:
                pass
            else:
                await message.delete()
                info_msg_id = 0

        bugemoji = Emoji.get_emoji('BUG')
        message = await channel.send(Lang.get_string("art/art_info", emoji=bugemoji))
        await message.add_reaction(bugemoji)
        Configuration.set_persistent_var(f"art_message_{guild_id}", message.id)

    def get_ro_art_info_message_id(self, guild_id):
        tracker = f"art_message_{guild_id}"
        return Configuration.get_persistent_var(tracker)

    async def send_art(self, user, trigger_channel):
        await asyncio.sleep(1)
        guild = self.bot.get_guild(Configuration.get_var("guild_id"))
        member = guild.get_member(user.id)
        # fully ignore muted users
        mute_role = guild.get_role(Configuration.get_var("muted_role"))
        if member is None:
            # user isn't even on the server, how did we get here?
            return
        if mute_role in member.roles:
            # muted, hard ignore
            return

        if user.id in self.in_progress:
            await self.delete_progress(user.id)

        # Start a bug report
        task = self.bot.loop.create_task(self.actual_art_sender(user, trigger_channel))
        self.in_progress[user.id] = task
        try:
            await task
        except CancelledError as ex:
            pass

    async def delete_progress(self, uid):
        if uid in self.in_progress:
            self.in_progress[uid].cancel()
            del self.in_progress[uid]

    async def actual_art_sender(self, user, trigger_channel):
        # wrap everything so users can't get stuck in limbo
        active_question = None
        art_count = 0
        art_max = 3
        channel = None

        try:
            channel = await user.create_dm()

            # vars to store everything
            asking = True
            attachment_links = []
            report = None
            title = ""
            description = ""
            mode = None

            # define all the parts we need as inner functions for easier sinfulness

            def question_mode(input_mode):
                nonlocal mode
                mode = input_mode

            async def abort():
                nonlocal asking
                await user.send(Lang.get_string("art/abort_submit"))
                asking = False
                await self.delete_progress(user.id)

            def max_length(length):
                def real_check(text):
                    if len(text) > length:
                        return Lang.get_string("art/text_too_long", max=length)
                    return True
                return real_check

            async def send_art():
                # send art
                nonlocal report
                c = self.ro_art_channels[trigger_channel.guild.id]
                message = await self.bot.get_channel(c).send(
                    content=Lang.get_string("art/report_header", user=user.mention), embed=report)
                if len(attachment_links) != 0:
                    key = "attachment_info" if len(attachment_links) == 1 else "attachment_info_plural"
                    attachment = await self.bot.get_channel(c).send(
                        Lang.get_string(f"art/{key}", id=0, links="\n".join(attachment_links)))
                await channel.send(Lang.get_string("art/report_confirmation", channel_id=c))
                await self.send_ro_art_info(channel)

            async def prompt_user():
                nonlocal mode
                nonlocal title
                nonlocal description
                nonlocal attachment_links
                if mode == "art":
                    print("art")
                    # ask for art, show count/max
                    attachment_links = await Questions.ask_attachements(self.bot, channel, user)
                    return
                if mode == "title":
                    # ask for title. if title exists show current and instruct new title overwrites.
                    title = await Questions.ask_text(self.bot,
                                                     channel,
                                                     user,
                                                     Lang.get_string("art/question_title",
                                                                     title=title),
                                                     validator=max_length(200))
                    return
                if mode == "description":
                    # ask for description. if description exists show current and instruct new description overwrites.
                    description = await Questions.ask_text(self.bot,
                                                           channel,
                                                           user,
                                                           Lang.get_string("art/question_description",
                                                                           description=description),
                                                           validator=max_length(1024))
                    return
                if mode == "submit":
                    print("submit")
                    # ask for review approval? then submit or ask again
                    return
                if mode == "cancel":
                    print("cancel")
                    # ask for cancel confirm
                    await abort()
                    return
                pass

            active_question = 0
            await Questions.ask(self.bot, channel, user, Lang.get_string("art/question_ready"),
                                [
                                    Questions.Option("YES", "Press this reaction to answer YES and send artwork"),
                                    Questions.Option("NO", "Press this reaction to answer NO", handler=abort),
                                ], show_embed=True)

            while asking:
                # multiple-choice looping:
                # a. artwork 0/3 attachments w counter
                # b. title
                # c. description
                # d. complete/send
                # e. discard/cancel

                # :frame_photo: - Artwork 0/3
                # :paintbrush: - Title
                # :scroll: - Description
                # :love_letter: - Done/Submit
                # :no_entry_sign: - Cancel/Discard

                await Questions.ask(self.bot, channel, user, Lang.get_string("art/question_mode"),
                                    [
                                        Questions.Option("ART", f"Artwork {art_count}/{art_max}", lambda: question_mode(self.art)),
                                        Questions.Option("BRUSH", "Title", lambda: question_mode(self.title)),
                                        Questions.Option("SCROLL", "Description", lambda: question_mode(self.description)),
                                        Questions.Option("LOVE_LETTER", "Done/Submit", lambda: question_mode(self.submit)),
                                        Questions.Option("NO", "Cancel/Discard", lambda: question_mode(self.cancel)),
                                    ], show_embed=True)

                await prompt_user()

                # assemble the final post and show to user for review
                report = Embed(timestamp=datetime.utcfromtimestamp(time.time()))

                # get author from guild, derive by-line from author nick/name
                author = trigger_channel.guild.get_member(user.id)
                author = author.nick or author.name
                report.set_author(name=f"Artwork by {author}", icon_url=user.avatar_url_as(size=32))
                if title:
                    report.add_field(name=Lang.get_string("art/title"), value=title, inline=False)
                if description:
                    report.add_field(name=Lang.get_string("art/description"), value=description, inline=False)

                # TODO: use file instead and post image directly instead of link
                if len(attachment_links) == 1:
                    url = str(attachment_links[0])
                    report.set_image(url=url)

                await channel.send(content=Lang.get_string("art/art_header", id="##", user=user.mention),
                                   embed=report)
                if attachment_links:
                    i = 0
                    for url in attachment_links:
                        i = i+1
                        # download attachment and put it in a buffer, then send the final images
                        u = requests.get(url)
                        content_type = u.headers['content-type']
                        extension = mimetypes.guess_extension(content_type)
                        f = io.StringIO()
                        buffer = io.BytesIO()
                        # use it as any other file here to write to it
                        buffer.write(u.content)
                        buffer.seek(0)  # reset the reader to the beginning
                        # TODO: add cleaned author name or other unique identifier to filename
                        await channel.send(file=discord.File(buffer, f"art_file_{i}.{extension}"))

            review_time = 300
            await asyncio.sleep(1)

            # Question 15 - final review
            await Questions.ask(self.bot, channel, user,
                                Lang.get_string("bugs/question_ok", timeout=Questions.timeout_format(review_time)),
                                [
                                    Questions.Option("YES", Lang.get_string("art/send_art"), send_art),
                                    Questions.Option("NO", Lang.get_string("art/cancel_submission"))
                                ], show_embed=True, timeout=review_time)

        except Forbidden as ex:
            await trigger_channel.send(
                Lang.get_string("bugs/dm_unable", user=user.mention),
                delete_after=30)
        except asyncio.TimeoutError as ex:
            if channel is not None:
                await channel.send(Lang.get_string("bugs/report_timeout"))
            self.bot.loop.create_task(self.delete_progress(user.id))
        except CancelledError as ex:
            pass
        except Exception as ex:
            self.bot.loop.create_task(self.delete_progress(user.id))
            await Utils.handle_exception("bug reporting", self.bot, ex)
            raise ex
        else:
            self.bot.loop.create_task(self.delete_progress(user.id))

    async def load_channels(self, guild):
        """
        set up collectors for all recorded art channels
        :param guild: guild object
        :return:
        """
        my_channels = dict()
        my_collection_channels = set()
        for row in ArtChannel.select().where(ArtChannel.serverid == guild.id):
            # [guildid][listen][tag] = [collect_to]
            l_id = row.listenchannelid
            c_id = row.collectionchannelid
            tag = row.tag or self.no_tag

            # listen channel is primary sort key
            if l_id not in my_channels:
                my_channels[l_id] = dict()

            # tagged items go to corresponding channel
            my_channels[l_id][tag] = c_id
            # flat set of channels that art is collected into, for easier listening
            my_collection_channels.add(c_id)

        self.collection_channels[guild.id] = my_collection_channels
        self.channels[guild.id] = my_channels

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.channels[guild.id] = dict()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.channels[guild.id]
        for row in ArtChannel.select().where(ArtChannel.serverid == guild.id):
            row.delete_instance()

    @commands.group(name="artchannel", aliases=['art_channel', 'artchan', 'ac'], invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def art_channel(self, ctx: commands.Context):
        """Show a list of art channels"""
        embed = discord.Embed(timestamp=ctx.message.created_at, color=0x663399, title=Lang.get_string("art/list_channels", server_name=ctx.guild.name))
        if len(self.channels[ctx.guild.id]) > 0:
            value = ""
            for listen_channel_id, collection in self.channels[ctx.guild.id].items():
                listen_channel_name = await Utils.clean(f"<#{listen_channel_id}>", guild=ctx.guild)
                for tag in collection.keys():
                    channel_id = collection[tag]
                    collect_channel_name = await Utils.clean(f"<#{channel_id}>", guild=ctx.guild)
                    if len(collect_channel_name) + len(f"{channel_id}") > 1000:
                        embed.add_field(name="\u200b", value=value)
                        value = ""
                    print_tag = '' if tag is self.no_tag else f"\"#{tag}\""
                    value = f"{value}**{listen_channel_name}** {print_tag} -> **{collect_channel_name}**\n"
            embed.add_field(name="\u200b", value=value)
            await ctx.send(embed=embed)
        else:
            await ctx.send(Lang.get_string("art/no_channels"))

    @art_channel.command(aliases=["new"])
    @commands.guild_only()
    async def add(self, ctx: commands.Context, listen_channel_id: int, collect_channel_id: int, tag: str = ""):
        """
        Add channel to art collector setup.
        :param ctx:
        :param listen_channel_id: id of channel to listen in
        :param collect_channel_id: id of channel to collect into
        :param tag: [no_tag|listen|any random tag to track]
        :return:
        """
        # TODO: use better Converter for channel_id
        # TODO: move "listen" tag to its own command, like "art_channel add_tracking_channel 12345"

        listen_channel_mention = f"<#{listen_channel_id}>"
        collect_channel_mention = f"<#{collect_channel_id}>"

        if CHANNEL_ID_MATCHER.fullmatch(listen_channel_mention) is None or ctx.guild.get_channel(listen_channel_id) is None:
            await ctx.send(f"No such channel to listen in: `{listen_channel_id}`")
            return

        if CHANNEL_ID_MATCHER.fullmatch(collect_channel_mention) is None or ctx.guild.get_channel(collect_channel_id) is None:
            await ctx.send(f"No such channel to collect into: `{collect_channel_id}`")
            return

        row = ArtChannel.get_or_none(serverid=ctx.guild.id,
                                     listenchannelid=listen_channel_id,
                                     collectionchannelid=collect_channel_id,
                                     tag=tag)
        listen_channel_name = await Utils.clean(listen_channel_mention, guild=ctx.guild)
        collect_channel_name = await Utils.clean(collect_channel_mention, guild=ctx.guild)
        if row is None:
            ArtChannel.create(serverid=ctx.guild.id,
                              listenchannelid=listen_channel_id,
                              collectionchannelid=collect_channel_id,
                              tag=tag)
            await self.startup_cleanup()
            channel_added_str = Lang.get_string('art/channel_added',
                                                listenchannel=listen_channel_mention,
                                                collectchannel=collect_channel_mention,
                                                tag=tag)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {channel_added_str}")
        else:
            await ctx.send(Lang.get_string('art/channel_found',
                                           listenchannel=listen_channel_mention,
                                           collectchannel=collect_channel_mention,
                                           tag=row.tag))

    @art_channel.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, listen_channel_id: int, collect_channel_id: int, tag=""):
        """command_remove_help"""
        key = tag or self.no_tag

        # Are we listening for tag in listenchannel, collecting into collectchannel?
        # must be very specific to remove from db.
        if listen_channel_id in self.channels[ctx.guild.id] and \
                key in self.channels[ctx.guild.id][listen_channel_id] and \
                self.channels[ctx.guild.id][listen_channel_id][key] == collect_channel_id:
            # TODO: fetch first, delete if exists, else message error
            try:
                ArtChannel.get(serverid=ctx.guild.id,
                               listenchannelid=listen_channel_id,
                               collectionchannelid=collect_channel_id,
                               tag=tag).delete_instance()
                await self.startup_cleanup()
                lc_mention = self.bot.get_channel(listen_channel_id).mention
                cc_mention = self.bot.get_channel(collect_channel_id).mention
                channel_removed_str = Lang.get_string('art/channel_removed',
                                                      listenchannel=lc_mention,
                                                      collectchannel=cc_mention,
                                                      tag=key)
                await ctx.send(f"{Emoji.get_chat_emoji('YES')} {channel_removed_str}")
            except Exception as ex:
                await ctx.send("That's not an art channel... or tag... or ?? something?")
                pass
        else:
            channel_not_found_str = Lang.get_string('art/channel_not_found',
                                                    listenchannel=listen_channel_id,
                                                    collectchannel=collect_channel_id,
                                                    tag=tag)
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} {channel_not_found_str}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Message listener. watch art channels for attachments. share attachments to collection channel
        optionally use tags to sort posts into tag collection channels.
        :param message:
        :return:
        """
        try:
            if message.author.bot\
                    or not message.attachments\
                    or not hasattr(message.channel, "guild")\
                    or message.channel.guild is None\
                    or message.channel.id not in self.channels[message.channel.guild.id]:
                return
        except KeyError as ex:
            return

        ctx = await self.bot.get_context(message)
        tags = []

        for tag in self.channels[ctx.guild.id][message.channel.id].keys():
            tags.append(f"\\b{re.escape(tag)}\\b")
        tag_pattern = '|'.join(tags)
        tag_matcher = re.compile(tag_pattern, re.IGNORECASE)
        tags = tag_matcher.findall(message.content)

        async def do_collect(my_message, my_tag):
            content_shown = False
            my_channel = self.bot.get_channel(self.channels[ctx.guild.id][my_message.channel.id][my_tag.lower()])
            for attachment in my_message.attachments:
                embed = discord.Embed(
                    timestamp=my_message.created_at,
                    color=0x663399)
                embed.add_field(name="Author", value=my_message.author.mention)
                if my_tag is not self.no_tag:
                    embed.add_field(name="Tag", value=f"#{my_tag}")
                embed.add_field(name="Jump Link", value=f"[Go to message]({my_message.jump_url})")
                embed.add_field(name="URL", value=f"[Download]({attachment.url})")
                if my_message.content and not content_shown:
                    # Add message content to the first of multiples, when many attachments to a single my_message.
                    embed.add_field(name="Message Content", value=my_message.content, inline=False)
                    content_shown = True
                embed.set_image(url=attachment.url)
                sent = await my_channel.send(embed=embed)
                await sent.add_reaction(Emoji.get_emoji("YES"))
                await sent.add_reaction(Emoji.get_emoji("NO"))

        if tags:
            for tag in tags:
                await do_collect(message, tag)
        else:
            await do_collect(message, self.no_tag)

    @commands.guild_only()
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        """
        reaction listener for art collection channels.
        Clears reactions and on "no" reaction, removes post from collection
        :param event:
        :return:
        """
        try:
            channel = self.bot.get_channel(event.channel_id)
            message = await channel.fetch_message(event.message_id)

            # listen for reactions to bot dialog
            if self.get_ro_art_info_message_id(channel.guild.id) == event.message_id:
                user = self.bot.get_user(event.user_id)
                if user.bot:
                    return
                await message.remove_reaction(event.emoji, user)
                await self.send_art(user, channel)
            elif event.channel_id in self.collection_channels[message.channel.guild.id]:
                member = message.channel.guild.get_member(event.user_id)
                user_is_bot = event.user_id == self.bot.user.id
                has_permission = member.guild_permissions.mute_members  # TODO: change to role-based?
                if user_is_bot or not has_permission:
                    return

                await message.clear_reactions()  # any reaction will remove the bot reacts
                if str(event.emoji) == str(Emoji.get_emoji("NO")):
                    # delete message
                    await message.delete()
                    return

        except (NotFound, HTTPException, KeyError, AttributeError) as e:
            # couldn't find channel, message, member, or action
            return
        except Exception as e:
            await Utils.handle_exception("art collector generic exception", self, e)
            return


def setup(bot):
    bot.add_cog(ArtCollector(bot))
