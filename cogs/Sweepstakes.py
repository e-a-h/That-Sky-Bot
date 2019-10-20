import os

from discord import File
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Utils, Logging
from datetime import datetime
from utils.Utils import save_to_disk


class Sweepstakes(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)

    async def cog_check(self, ctx):
        if not hasattr(ctx.author, 'guild'):
            return False
        # TODO: should this be admin and/or custom role?
        return ctx.author.guild_permissions.manage_channels

    def get_unique_react_users(self, user_list: dict):
        fields = ["id", "nick", "username", "discriminator", "mention", "left_guild"]
        data_list = ()
        for user_id, user in user_list.items():
            if hasattr(user, "nick"):
                nick = user.nick
                left_guild = ""
            else:
                nick = ""
                left_guild = "USER LEFT GUILD"
            data_list += ({"id": user.id,
                           "nick": nick,
                           "username": user.name,
                           "discriminator": user.discriminator,
                           "mention": user.mention,
                           "left_guild": left_guild},)
        out = ""
        for i in data_list:
            out += str(i) + "\n"
        return {'fields': fields, 'data': data_list}

    async def send_csv(self, ctx, fields: list, data: tuple):
        now = datetime.today().timestamp()
        save_to_disk(f"entries_{now}", data, 'csv', fields)
        send_file = File(f"entries_{now}.csv")
        await ctx.send(file=send_file)
        os.remove(f"entries_{now}.csv")

    @commands.group(name="sweeps")
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def sweepstakes(self, ctx: commands.Context):
        """sweeps help"""
        if ctx.invoked_subcommand is None:
            pass

    @sweepstakes.command(aliases=["csv", "report"])
    @commands.guild_only()
    async def entries(self, ctx: commands.Context, jump_url: str):
        """get a list of reactions to a given message"""
        parts = jump_url.split('/')
        channel_id = parts[-2]
        message_id = parts[-1]
        try:
            channel = await self.bot.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            reaction_list = {}
            # TODO: remove author from this list
            for reaction in message.reactions:
                async for user in reaction.users():
                    reaction_list[user.id] = user
                # winner = random.choice(reaction_list)
                # await channel.send('{} has won the raffle.'.format(winner))
            unique_users = self.get_unique_react_users(reaction_list)
            await ctx.send(f"There are {len(unique_users['data'])} entries (unique reactions) to this drawing.")
            await self.send_csv(ctx, unique_users['fields'], unique_users['data'])
        except Exception as e:
            await Utils.handle_exception(f"Failed to get entries {channel_id}/{message_id}", self, e)
            await ctx.send(f"Failed to get entries {channel_id}/{message_id}")
        # ?sweeps reactions 621746950458572801/624267628080267264


def setup(bot):
    bot.add_cog(Sweepstakes(bot))
