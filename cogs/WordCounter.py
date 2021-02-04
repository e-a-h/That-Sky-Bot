import re

import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Lang, Utils, Emoji, Configuration
from utils.Database import CountWord


class WordCounter(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.words = dict()
        self.loaded = False
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        for guild in self.bot.guilds:
            my_words = set()
            # fetch words and build matching pattern
            for row in CountWord.select(CountWord.word).where(CountWord.serverid == guild.id):
                my_words.add(re.escape(row.word))
            self.words[guild.id] = "|".join(my_words)
        self.loaded = True

    async def cog_check(self, ctx):
        if ctx.guild is None:
            return False
        return ctx.author.guild_permissions.ban_members

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.words[guild.id] = ""

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.words[guild.id]
        for word in CountWord.select().where(CountWord.serverid == guild.id):
            word.delete_instance()

    @commands.group(name="wordcounter", aliases=['wordcount', 'word_count', 'countword', 'count_word'], invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def word_counter(self, ctx: commands.Context):
        """Show a list of counted words"""
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("word_counter/list_words", ctx, server_name=ctx.guild.name))

        word_list = set()
        for row in CountWord.select(CountWord.word).where(CountWord.serverid == ctx.guild.id):
            word_list.add(row.word)

        if word_list != set():
            # word list is not empty set
            value = ""
            for word in word_list:
                word_cleaned = re.escape(word)
                if len(value) + len(word_cleaned) > 1000:
                    embed.add_field(name="\u200b", value=value)
                    value = ""
                value = f"{value}{word_cleaned}\n"
            embed.add_field(name="\u200b", value=value)
            await ctx.send(embed=embed)
        else:
            await ctx.send(Lang.get_locale_string("word_counter/no_words", ctx))

    @word_counter.command(aliases=["new"])
    @commands.guild_only()
    async def add(self, ctx: commands.Context, *, word: str):
        """command_add_help"""
        row = CountWord.get_or_none(serverid=ctx.guild.id, word=word)
        if row is None:
            CountWord.create(serverid = ctx.guild.id, word=word)
            await self.startup_cleanup()
            emoji = Emoji.get_chat_emoji('YES')
            msg = Lang.get_locale_string('word_counter/word_added', ctx, word=word)
            await ctx.send(f"{emoji} {msg}")
        else:
            await ctx.send(Lang.get_locale_string('word_counter/word_found', ctx, word=word))

    @word_counter.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx:commands.Context, *, word):
        """command_remove_help"""
        row = CountWord.get_or_none(serverid=ctx.guild.id, word=word)
        if row is not None:
            row.delete_instance()
            await self.startup_cleanup()
            emoji = Emoji.get_chat_emoji('YES')
            msg = Lang.get_locale_string('word_counter/word_removed', ctx, word=word)
        else:
            emoji = Emoji.get_chat_emoji('NO')
            msg = Lang.get_locale_string('word_counter/word_not_found', ctx, word=word)
        await ctx.send(f"{emoji} {msg}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        prefix = Configuration.get_var("bot_prefix")
        is_boss = await self.cog_check(message)
        command_context = message.content.startswith(prefix, 0) and is_boss
        not_in_guild = not hasattr(message.channel, "guild") or message.channel.guild is None

        if command_context or not_in_guild:
            return

        m = self.bot.metrics
        pattern = re.compile(self.words[message.guild.id], re.IGNORECASE)
        # find all matches and reduce to unique set
        words = set(pattern.findall(message.content))
        for word in words:
            # increment counters
            word = str(word).lower()
            m.word_counter.labels(word=word).inc()


def setup(bot):
    bot.add_cog(WordCounter(bot))
