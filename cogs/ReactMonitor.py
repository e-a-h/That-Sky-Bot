from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Utils

banned_emoji = ["🖕", "🍆"]
watched_emoji = ["✡️", "☪️", "✝️", "🔫", "💩"]
# TODO: move emoji to db, add commands for adding/removing
# TODO: option for mute if mute role is set. config command to set/unset mute role
muted_roles = {
    621746949485232154: 624294429838147634,
    575762611111592007: 600490107472052244
}


class ReactMonitor(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        emoji_used = str(event.emoji)
        member = event.member
        guild = self.bot.get_guild(event.guild_id)
        channel = self.bot.get_channel(event.channel_id)
        message = await channel.fetch_message(event.message_id)
        log_channel = self.bot.get_config_channel(message.guild.id, Utils.log_channel)
        if emoji_used in banned_emoji:
            await message.clear_reaction(emoji_used)
            muted_role = guild.get_role(muted_roles[guild.id])
            await member.add_roles(muted_role)
            # ping log channel with detail
            if log_channel:
                await log_channel.send(f"I muted {member.mention} for using blacklisted emoji {emoji_used} in #{channel.name}.\n"
                                       f"{message.jump_url}")
        if emoji_used in watched_emoji:
            # ping log channel with detail
            if log_channel:
                await log_channel.send(f"{member.mention} used watched emoji {emoji_used} in #{channel.name}.\n"
                                       f"{message.jump_url}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, event):
        emoji_used = str(event.emoji)
        guild = self.bot.get_guild(event.guild_id)
        member = guild.get_member(event.user_id)
        channel = self.bot.get_channel(event.channel_id)
        message = await channel.fetch_message(event.message_id)
        print(event)
        log_channel = self.bot.get_config_channel(guild.id, Utils.log_channel)
        # ping log channel with detail
        if log_channel:
            await log_channel.send(f"{member.mention} removed reaction {emoji_used} from a message in {channel.mention}\n"
                                   f"{message.jump_url}")


def setup(bot):
    bot.add_cog(ReactMonitor(bot))
