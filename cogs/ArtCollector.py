import re

import discord
from discord import NotFound
from discord.ext import commands

from utils import Lang, Utils, Emoji
from utils.Database import ArtChannel

from cogs.BaseCog import BaseCog
from utils.Utils import CHANNEL_ID_MATCHER


class ArtCollector(BaseCog):

    main_tag = "main_tag"
    listen_tag = "listen"

    async def cog_check(self, ctx):
        return ctx.author.guild_permissions.ban_members

    def __init__(self, bot):
        super().__init__(bot)
        self.channels = dict()
        self.collection_channels = dict()
        self.loaded = False
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        # Load channels
        for guild in self.bot.guilds:
            my_channels = dict()
            my_listen_channels = set()
            main_channel = False
            for row in ArtChannel.select().where(ArtChannel.serverid == guild.id):
                tag = row.tag
                if row.tag == "":
                    if main_channel:
                        # more than one main channel error
                        raise Exception("too many main art channels. fix your db!")
                    tag = self.main_tag
                my_channels[tag] = row.channelid
                if row.tag != self.listen_tag:
                    my_listen_channels.add(row.channelid)

            self.collection_channels[guild.id] = my_listen_channels
            self.channels[guild.id] = my_channels
        self.loaded = True

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.channels[guild.id] = dict()
        self.collection_channels[guild.id] = set()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.channels[guild.id]
        del self.collection_channels[guild.id]
        for row in ArtChannel.select().where(ArtChannel.serverid == guild.id):
            row.delete_instance()

    @commands.group(name="artchannel", aliases=['artchan', 'ac'], invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def art_channel(self, ctx: commands.Context):
        """Show a list of art channels"""
        embed = discord.Embed(timestamp=ctx.message.created_at, color=0x663399, title=Lang.get_string("art/list_channels", server_name=ctx.guild.name))
        if len(self.channels[ctx.guild.id]) > 0:
            value = ""
            for tag, channel_id in self.channels[ctx.guild.id].items():
                channel_name = await Utils.clean(f"<#{channel_id}>", guild=ctx.guild)
                if len(channel_name) + len(f"{channel_id}") > 1000:
                    embed.add_field(name="\u200b", value=value)
                    value = ""
                value = f"{value}#{tag} -> {channel_name} - id:{channel_id}\n"
            embed.add_field(name="\u200b", value=value)
            await ctx.send(embed=embed)
        else:
            await ctx.send(Lang.get_string("art/no_channels"))

    @art_channel.command(aliases=["new"])
    @commands.guild_only()
    async def add(self, ctx: commands.Context, channel_id: str, tag: str = ""):
        """command_add_help"""
        # TODO: use Converter for channel_id
        channel_id = int(channel_id)
        channel = f"<#{channel_id}>"

        if CHANNEL_ID_MATCHER.fullmatch(channel) is None or ctx.guild.get_channel(channel_id) is None:
            await ctx.send(f"No such channel: `{channel_id}`")
            return

        if tag == "" or tag == self.main_tag:
            mains = ArtChannel.select().where((ArtChannel.serverid == ctx.guild.id) & (ArtChannel.tag == ""))
            if len(mains) != 0:
                await ctx.send("Can't add another main channel. Only one allowed.")
                return

        row = ArtChannel.get_or_none(serverid=ctx.guild.id, channelid=channel_id, tag=tag)
        channel_name = await Utils.clean(channel, guild=ctx.guild)
        if row is None:
            ArtChannel.create(serverid=ctx.guild.id, channelid=channel_id, tag=tag)
            await self.startup_cleanup()
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('art/channel_added', channel=channel_name, tag=tag)}")
        else:
            await ctx.send(Lang.get_string('art/channel_found', channel=channel_name, tag=row.tag))

    @art_channel.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, channel_id, tag=""):
        """command_remove_help"""
        channel_id = int(channel_id)
        key = tag or self.main_tag

        if key in self.channels[ctx.guild.id].keys():
            # TODO: fetch first, delete if exists, else message error
            try:
                ArtChannel.get(serverid=ctx.guild.id, channelid=channel_id, tag=tag).delete_instance()
                await self.startup_cleanup()
                await ctx.send(f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('art/channel_removed', channel=channel_id, tag=key)}")
            except Exception as ex:
                await ctx.send("That's not an art channel... or tag... or ?? something?")
                pass
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} {Lang.get_string('art/channel_not_found', channel=channel_id, tag=tag)}")

    @commands.guild_only()
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            if message.author.bot\
                    or not message.attachments\
                    or not hasattr(message.channel, "guild")\
                    or message.channel.guild is None\
                    or message.channel.id != self.channels[message.channel.guild.id][self.listen_tag]:
                return
        except KeyError as ex:
            return

        ctx = await self.bot.get_context(message)
        tags = []

        for tag in self.channels[ctx.guild.id].keys():
            tags.append(f"\\b{re.escape(tag)}\\b")
        tag_pattern = '|'.join(tags)
        tag_matcher = re.compile(tag_pattern, re.IGNORECASE)
        tags = tag_matcher.findall(message.content)

        if tags:
            for tag in tags:
                channel = self.bot.get_channel(self.channels[ctx.guild.id][tag])
                for attachment in message.attachments:
                    embed = discord.Embed(
                        timestamp=message.created_at,
                        color=0x663399)
                    embed.add_field(name="Author", value=message.author.mention)
                    embed.add_field(name="Tag", value=f"#{tag}")
                    embed.add_field(name="Jump Link", value=f"[Go to message]({message.jump_url})")
                    embed.add_field(name="URL", value=f"[Download]({attachment.url})")
                    if message.content:
                        embed.add_field(name="Message Content", value=message.content)
                    embed.set_image(url=attachment.url)
                    sent = await channel.send(embed=embed)
                    await sent.add_reaction(Emoji.get_emoji("YES"))
                    await sent.add_reaction(Emoji.get_emoji("NO"))
        else:
            channel = self.bot.get_channel(self.channels[ctx.guild.id][self.main_tag])
            for attachment in message.attachments:
                embed = discord.Embed(
                    timestamp=message.created_at,
                    color=0x663399)
                embed.add_field(name="Author", value=message.author.mention)
                embed.add_field(name="Jump Link", value=f"[Go to message]({message.jump_url})")
                embed.add_field(name="URL", value=f"[Download]({attachment.url})")
                if message.content:
                    embed.add_field(name="Message Content", value=message.content)
                embed.set_image(url=attachment.url)
                sent = await channel.send(embed=embed)
                await sent.add_reaction(Emoji.get_emoji("YES"))
                await sent.add_reaction(Emoji.get_emoji("NO"))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
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

            await message.clear_reactions()
            if str(event.emoji) == str(Emoji.get_emoji("NO")):
                # delete message
                await message.delete()
                return

        except (NotFound, KeyError, AttributeError) as e:
            # couldn't find channel, message, member, or action
            return
        except Exception as e:
            await Utils.handle_exception("art collector generic exception", self, e)
            return


def setup(bot):
    bot.add_cog(ArtCollector(bot))
