from discord import Message, Reaction, TextChannel
from discord.ext import commands
from discord.ext.commands import Context, command

from cogs.BaseCog import BaseCog
from sky import Skybot
from utils import Configuration, Logging, Emoji


class Welcomer(BaseCog):
    @command()
    async def welcome(self, ctx: Context):
        """welcomer_help"""
        txt = Configuration.get_var("welcome_msg")
        Logging.info(ctx)
        rules = self.bot.get_channel(Configuration.get_var('rules_channel'))
        await ctx.send(txt.format(ctx.author.mention, rules.mention))

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        print(message)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        txt = Configuration.get_var("welcome_msg")
        rules_channel = self.bot.get_channel(Configuration.get_var('rules_channel'))
        welcome_channel = self.bot.get_channel(Configuration.get_var('welcome_channel'))
        txt = txt.format(member.mention, rules_channel.mention)
        Logging.info(txt)
        if welcome_channel is not None:
            await welcome_channel.send(txt)


async def init_rules_reaction(bot):
    rules_channel_id = Configuration.get_var('rules_channel')
    rules_message_id = Configuration.get_var('rules_react_message_id')
    new_member_role = Configuration.get_var('new_member_role')
    emoji = Emoji.get_emoji("CANDLE")
    rules_channel: TextChannel = bot.get_channel(rules_channel_id)
    rules_message: Message = await rules_channel.fetch_message(rules_message_id)

    def check(reaction: Reaction, user):
        return user != bot.user and str(reaction.emoji) == emoji and reaction.message.id == rules_message_id

    while True:
        reaction, user = await bot.wait_for('reaction_add', check=check)
        if user:
            user.add_roles(new_member_role)
            Logging.info(f"{user.mention} added a reaction!")


def setup(bot):
    bot.add_cog(Welcomer(bot))
