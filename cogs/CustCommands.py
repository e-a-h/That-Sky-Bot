import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Configuration, Emoji, Lang, Utils, Questions
from utils.Database import CustomCommand


class CustCommands(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)

        self.commands = dict()
        self.bot.loop.create_task(self.reload_commands())
        self.loaded = False

    async def cog_check (self, ctx):
        return ctx.author.guild_permissions.ban_members

    async def reload_commands(self):
        for guild in self.bot.guilds:
            self.commands[guild.id] = dict()
            for command in CustomCommand.select().where(CustomCommand.serverid == guild.id):
                self.commands[guild.id][command.trigger] = command.response
        self.loaded = True

    @staticmethod
    async def send_response(ctx, emoji_name, lang_key, **kwargs):
        msg = Lang.get_locale_string(f'custom_commands/{lang_key}', ctx, **kwargs)
        emoji = Emoji.get_chat_emoji(emoji_name)
        await ctx.send(f"{emoji} {msg}")

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
            embed = discord.Embed(
                timestamp=ctx.message.created_at,
                color=0x663399,
                title=Lang.get_locale_string("custom_commands/list_commands", ctx, server_name=ctx.guild.name))
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
                await ctx.send(Lang.get_locale_string("custom_commands/no_commands", ctx))

    @command.command(aliases=["new", "add"])
    @commands.guild_only()
    async def create(self, ctx: commands.Context, trigger: str, *, reply: str = None):
        """command_create_help"""
        if len(trigger) == 0:
            await self.send_response(ctx, "WHAT", 'empty_trigger')
        elif reply is None or reply == "":
            await self.send_response(ctx, "WHAT", 'empty_reply')
        elif len(trigger) > 20:
            await self.send_response(ctx, "WHAT", 'trigger_too_long')
        else:
            trigger = trigger.lower()
            trigger = await Utils.clean(trigger)
            command = CustomCommand.get_or_none(serverid=ctx.guild.id, trigger=trigger)
            if command is None:
                CustomCommand.create(serverid=ctx.guild.id, trigger=trigger, response=reply)
                self.commands[ctx.guild.id][trigger] = reply
                msg = Lang.get_locale_string('custom_commands/command_added', ctx, trigger=trigger)
                await ctx.send(f"{Emoji.get_chat_emoji('YES')} {msg}")
            else:
                async def yes():
                    await ctx.send(Lang.get_locale_string('custom_commands/updating_command', ctx))
                    await ctx.invoke(self.update, trigger, reply=reply)

                async def no():
                    await ctx.send(Lang.get_locale_string('custom_commands/not_updating_command', ctx))

                await Questions.ask(self.bot,
                                    ctx.channel,
                                    ctx.author,
                                    Lang.get_locale_string('custom_commands/override_confirmation', ctx),
                                    [
                                        Questions.Option('YES', handler=yes),
                                        Questions.Option('NO', handler=no)
                                    ], delete_after=True, locale=ctx)

    @command.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx:commands.Context, trigger:str):
        """command_remove_help"""
        trigger = trigger.lower()
        trigger = await Utils.clean(trigger)

        tokens = dict()
        if len(trigger) > 20:
            emoji = 'WHAT'
            lang_key = 'trigger_too_long'
        elif trigger in self.commands[ctx.guild.id]:
            CustomCommand.get(serverid=ctx.guild.id, trigger=trigger).delete_instance()
            del self.commands[ctx.guild.id][trigger]
            emoji = 'YES'
            lang_key = 'command_removed'
            tokens = dict(trigger=trigger)
        else:
            emoji = 'NO'
            lang_key = 'not_found'
            tokens = dict(trigger=trigger)
        await self.send_response(ctx, emoji, lang_key, **tokens)

    @command.command(aliases=["edit", "set"])
    @commands.guild_only()
    async def update(self, ctx:commands.Context, trigger:str, *, reply:str = None):
        """command_update_help"""
        trigger = trigger.lower()
        trigger = await Utils.clean(trigger)
        tokens = dict()
        if reply is None:
            emoji = 'NO'
            msg = 'empty_reply'
        else:
            command = CustomCommand.get_or_none(serverid=ctx.guild.id, trigger=trigger)
            if command is None:
                emoji = 'WARNING'
                msg = 'creating_command'
                await ctx.invoke(self.create, trigger, reply=reply)
            else:
                command.response = reply
                command.save()
                self.commands[ctx.guild.id][trigger] = reply
                emoji = 'YES'
                msg = 'command_updated'
                tokens = dict(trigger=trigger)

        await self.send_response(ctx, emoji, msg, **tokens)

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
