import re

import discord
from discord import NotFound, HTTPException
from discord.ext import commands

from utils import Lang, Utils, Emoji
from utils.Database import ArtChannel

from cogs.BaseCog import BaseCog
from utils.Utils import CHANNEL_ID_MATCHER


class ArtCollector(BaseCog):

    no_tag = "no_tag"
    listen_tag = "listen"

    async def cog_check(self, ctx):
        return ctx.author.guild_permissions.ban_members

    def __init__(self, bot):
        super().__init__(bot)
        self.channels = dict()
        self.collection_channels = dict()
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        # Load channels
        for guild in self.bot.guilds:
            await self.load_channels(guild)

    async def load_channels(self, guild):
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

    @commands.guild_only()
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Message listener. watch art channels for attachments. share attachments to collection channel
        optionally use tags for sort posts into tag collection channels.
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

            if event.channel_id not in self.collection_channels[message.channel.guild.id]:
                return

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
