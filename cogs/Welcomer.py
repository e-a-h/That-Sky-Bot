import asyncio

import discord
from discord import Message, Reaction, TextChannel, utils
from discord.ext import commands
from discord.ext.commands import Context, command
from discord.utils import find

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

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        emoji = Emoji.get_emoji("CANDLE")
        react_user_id = event.user_id
        user = discord.Client.get_user(self.bot, react_user_id)
        rules_channel_id = Configuration.get_var('rules_channel')
        rules_message_id = Configuration.get_var('rules_react_message_id')
        rules_channel: TextChannel = self.bot.get_channel(rules_channel_id)
        new_member_role_id = Configuration.get_var('new_member_role')
        new_member_role = find(lambda r: r.id == new_member_role_id, rules_channel.guild.roles)

        if user != self.bot.user and str(event.emoji) == emoji and event.message_id == rules_message_id:
            member = discord.utils.find(lambda u: u.id == react_user_id, rules_channel.guild.members)
            await member.add_roles(new_member_role)
            await Logging.bot_log(f"{member.mention} got past the bouncer!")


def setup(bot):
    bot.add_cog(Welcomer(bot))
