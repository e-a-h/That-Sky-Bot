import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Configuration, Emoji, Lang, Utils, Questions
from utils.Database import CustomCommand


class CustCommands(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)

        self.commands = dict()
        self.bot.loop.create_task(self.reloadCommands())
        self.loaded = False

    async def cog_check (self, ctx):
        return ctx.author.guild_permissions.ban_members

    async def reloadCommands(self):
        for guild in self.bot.guilds:
            self.commands[guild.id] = dict()
            for command in CustomCommand.select().where(CustomCommand.serverid == guild.id):
                self.commands[guild.id][command.trigger] = command.response
        self.loaded = True

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.commands[guild.id] = dict()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.commands[guild.id]
        for command in CustomCommand.select().where(CustomCommand.serverid == guild.id):
            command.delete_instance()

    @commands.group(name="commands", aliases=['command'])
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def command(self, ctx: commands.Context):
        """Show a list of custom commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(timestamp=ctx.message.created_at, color=0x663399, title=Lang.get_string("custom_commands/list_commands", server_name=ctx.guild.name))
            value = ""
            if len(self.commands[ctx.guild.id].keys()) > 0:
                for trigger in self.commands[ctx.guild.id].keys():
                    if len(value) + len(trigger) > 1000:
                        embed.add_field(name="\u200b", value=value)
                        value = ""
                    value = f"{value}{trigger}\n"
                embed.add_field(name="\u200b", value=value)
                await ctx.send(embed=embed)
            else:
                await ctx.send(Lang.get_string("custom_commands/no_commands"))

    @command.command(aliases=["new", "add"])
    @commands.guild_only()
    async def create(self, ctx: commands.Context, trigger: str, *, reply: str = None):
        """command_create_help"""
        if len(trigger) == 0:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('custom_commands/empty_trigger')}")
        elif reply is None or reply == "":
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('custom_commands/empty_reply')}")
        elif len(trigger) > 20:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('custom_commands/trigger_too_long')}")
        else:
            trigger = trigger.lower()
            trigger = await Utils.clean(trigger)
            command = CustomCommand.get_or_none(serverid=ctx.guild.id, trigger=trigger)
            if command is None:
                CustomCommand.create(serverid = ctx.guild.id, trigger=trigger, response=reply)
                self.commands[ctx.guild.id][trigger] = reply
                await ctx.send(f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('custom_commands/command_added', trigger=trigger)}")
            else:
                async def yes():
                    await ctx.send(Lang.get_string('custom_commands/updating_command'))
                    await ctx.invoke(self.update, trigger, reply=reply)
                async def no():
                    await ctx.send(Lang.get_string('custom_commands/not_updating_command'))

                await Questions.ask(self.bot, ctx.channel, ctx.author, Lang.get_string('custom_commands/override_confirmation'),
                                    [
                                        Questions.Option('YES', handler=yes),
                                        Questions.Option('NO', handler=no)
                                    ], delete_after=True)

    @command.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx:commands.Context, trigger:str):
        """command_remove_help"""
        trigger = trigger.lower()
        trigger = await Utils.clean(trigger)
        if len(trigger) > 20:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_string('custom_commands/trigger_too_long')}")
        elif trigger in self.commands[ctx.guild.id]:
            CustomCommand.get(serverid = ctx.guild.id, trigger=trigger).delete_instance()
            del self.commands[ctx.guild.id][trigger]
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('custom_commands/command_removed', trigger=trigger)}")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} {Lang.get_string('custom_commands/not_found', trigger=trigger)}")

    @command.command(aliases=["edit", "set"])
    @commands.guild_only()
    async def update(self, ctx:commands.Context, trigger:str, *, reply:str = None):
        """command_update_help"""
        trigger = trigger.lower()
        trigger = await Utils.clean(trigger)
        if reply is None:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} {Lang.get_string('custom_commands/empty_reply')}")
        else:
            command = CustomCommand.get_or_none(serverid = ctx.guild.id, trigger=trigger)
            if command is None:
                await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} {Lang.get_string('custom_commands/creating_command')}")
                await ctx.invoke(self.create, trigger, reply=reply)
            else:
                command.response = reply
                command.save()
                self.commands[ctx.guild.id][trigger] = reply
                await ctx.send(f"{Emoji.get_chat_emoji('YES')} {Lang.get_string('custom_commands/command_updated', trigger=trigger)}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not hasattr(message.channel, "guild") or message.channel.guild is None:
            return
        prefix = Configuration.get_var("bot_prefix")
        if message.content.startswith(prefix, 0):
            for trigger in self.commands[message.guild.id]:
                if message.content.lower() == prefix+trigger or (message.content.lower().startswith(trigger, len(prefix)) and message.content.lower()[len(prefix+trigger)] == " "):
                    command_content = self.commands[message.guild.id][trigger].replace("@", "@\u200b")
                    await message.channel.send(command_content)


def setup(bot):
    bot.add_cog(CustCommands(bot))
