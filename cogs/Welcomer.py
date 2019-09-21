from discord.ext import commands
from cogs.BaseCog import BaseCog
from utils import Configuration, Logging, Emoji


class Welcomer(BaseCog):
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id == Configuration.get_var("guild_id"):
            txt = Configuration.get_var("welcome_msg")
            welcome_channel = self.bot.get_channel(Configuration.get_var('welcome_channel'))
            txt = txt.format(user=member.mention)
            if welcome_channel is not None:
                await welcome_channel.send(txt)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        react_user_id = event.user_id
        Logging.info(react_user_id)
        rules_message_id = Configuration.get_var('rules_react_message_id')
        Logging.info(rules_message_id)
        Logging.info(event.message_id)
        Logging.info(str(event.emoji))
        if react_user_id != self.bot.user.id and event.message_id == rules_message_id:
            await self.handle_reaction_change("add", str(event.emoji), react_user_id)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, event):
        react_user_id = event.user_id
        rules_message_id = Configuration.get_var('rules_react_message_id')
        if react_user_id != self.bot.user.id and event.message_id == rules_message_id:
            await self.handle_reaction_change("remove", str(event.emoji), react_user_id)

    async def handle_reaction_change(self, t, reaction, user_id):
        roles = Configuration.get_var("roles")
        Logging.info(roles)
        if reaction in roles:
            guild = self.bot.get_guild(Configuration.get_var("guild_id"))
            role = guild.get_role(roles[reaction])
            member = guild.get_member(user_id)
            Logging.info(role)
            Logging.info(member)
            action = getattr(member, f"{t}_roles")
            await action(role)


def setup(bot):
    bot.add_cog(Welcomer(bot))
