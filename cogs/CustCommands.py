import asyncio
import re
from itertools import islice
from typing import Union, Literal, Optional, Dict

import discord
from discord import Permissions, User, AllowedMentions, Guild
from discord import app_commands
from discord.app_commands import Group, Range, MissingPermissions, AppCommandError, Choice
from discord.ext import commands
from discord.ext.commands import Context, CommandError
from discord.interactions import Interaction
from tortoise.exceptions import IntegrityError

from cogs.BaseCog import BaseCog
from utils import Configuration, Emoji, Lang, Utils, Questions, Logging
from utils.Database import CustomCommand, CustomCommandContext
from utils.Helper import Sender, ConfirmView
from utils.Utils import interaction_response, trim_message


class CustCommands(BaseCog):

    trigger_max_length = 20

    def __init__(self, bot):
        super().__init__(bot)
        self.commands: Dict[int, Dict[str, CustomCommand]] = dict()

    async def cog_check(self, ctx):
        Logging.info(f"{self.__class__.__name__} cog check")
        allowed = (ctx.guild and ctx.author.guild_permissions.ban_members) or await Utils.permission_manage_bot(ctx)
        return allowed

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        for guild in self.bot.guilds:
            await self.init_guild(guild)

    async def init_guild(self, guild):
        self.commands[guild.id] = dict()
        for command in await CustomCommand.filter(serverid=guild.id):
            self.commands[guild.id][command.trigger] = command

    @staticmethod
    async def send_response(ctx: Union[Context, Interaction], emoji_name, lang_key, **kwargs):
        if 'trigger' in kwargs:
            kwargs['trigger'] = kwargs['trigger'].encode('utf-8').decode('unicode-escape')

        msg = Lang.get_locale_string(f'custom_commands/{lang_key}', ctx, **kwargs)
        emoji = Emoji.get_chat_emoji(emoji_name)
        if 'followup' in kwargs and kwargs['followup']:
            ephemeral = 'ephemeral' in kwargs and kwargs['ephemeral']
            await ctx.followup.send(f'{emoji} {msg}', ephemeral=ephemeral)
        else:
            sender = Sender(ctx)
            await sender.send(f"{emoji} {msg}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.commands[guild.id] = dict()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.commands[guild.id]
        await CustomCommand.filter(serverid=guild.id).delete()

    ####################
    # app commands
    ####################

    @app_commands.guild_only()
    @app_commands.command(name='enlighten')
    async def do_command(self, interaction: Interaction, topic: str, to: Optional[User] = None) -> None:
        """
        Perform a custom commands

        Parameters
        ----------
        interaction
        topic
            green friends in a pod
        to
            Someone to ping in my response

        Returns
        -------
        None
        """
        # cleaned_topic = await Utils.clean(topic)
        for trigger in self.commands[interaction.guild.id]:
            if topic == trigger:
                command: CustomCommand = self.commands[interaction.guild.id][trigger]
                if command.allowedcontext not in [CustomCommandContext.all, CustomCommandContext.app]:
                    await interaction_response(interaction).send_message(
                        f"The command `{command.trigger}` may only be used in "
                        f"`app command` contexts\n"
                        f"(hint, try `{Configuration.get_var('bot_prefix')}{trigger}`)",
                        ephemeral=True)
                    return
                if command.elevated > 0:
                    # TODO: map elevated value to permission level
                    # for now, greater than zero means "moderator"
                    if not interaction.permissions.ban_members:
                        raise MissingPermissions([""])
                command_content = command.response.replace("@", "@\u200b").format(author=interaction.user.mention)
                ephemeral = command.ephemeral

                # don't bother with @ when message is ephemeral
                if to and not ephemeral:
                    command_content = f"{to.mention}, {interaction.user.mention} asked me to enlighten you about `{trigger}`:\n{command_content}"

                allowed_mentions = AllowedMentions(everyone=False, roles=False, users=True)
                await interaction_response(interaction).send_message(
                    command_content,
                    ephemeral=ephemeral,
                    allowed_mentions=allowed_mentions)
                return
        await interaction_response(interaction).send_message(f"I don't know anything about that", ephemeral=True)

    config_group = Group(
        name='custom_command',
        description='Custom command configuration',
        guild_only=True,
        default_permissions=Permissions(ban_members=True))

    @config_group.command(name='list')
    async def list_commands(self, interaction: Interaction) -> None:
        """List custom commands"""
        await self.send_command_list(interaction)

    @config_group.command(name='add')
    async def add_command(self, interaction: Interaction, trigger: Range[str, 1, trigger_max_length], response: str) -> None:
        """Add a custom command"""
        await interaction_response(interaction).defer()

        cleaned_trigger = await Utils.clean(trigger.lower())
        command = await CustomCommand.get_or_none(serverid=interaction.guild.id, trigger=cleaned_trigger)
        if command is None:
            if await self.do_create(interaction.guild, cleaned_trigger, response):
                await self.send_response(interaction, "YES", 'command_added', trigger=cleaned_trigger)
                return
            else:
                raise CommandError("Failed to create custom command")

        # Command exists. Ask for confirmation to overwrite
        view = ConfirmView(interaction.user)
        await interaction.followup.send(
            Lang.get_locale_string('custom_commands/override_confirmation', interaction),
            view=view)

        await view.wait()

        if view.value is None:
            await interaction.followup.send(
                Lang.get_locale_string('common/interaction_timeout', interaction, description="Add command"))
        elif view.value:
            try:
                await self.do_update(interaction.guild, command, cleaned_trigger, response)
                await self.send_response(
                    interaction,
                    "YES",
                    'command_updated',
                    trigger=cleaned_trigger,
                    followup=True)
            except:
                raise CommandError("Failed to update custom command")
        else:
            await interaction.followup.send(Lang.get_locale_string('custom_commands/not_updating_command', interaction))

    @config_group.command(name='remove')
    async def remove_command(self, interaction: Interaction, trigger: Range[str, 1, trigger_max_length]) -> None:
        """Remove a custom command"""
        await interaction_response(interaction).defer(ephemeral=True)

        my_trigger, my_command = await self.match_trigger(interaction.guild, trigger)
        msg = (f"Are you sure you want to remove the command `{my_command.trigger}`? The command response is:\n"
               f"```{trim_message(my_command.response, 300)}```")
        view = ConfirmView(interaction.user)
        await interaction.followup.send(msg, view=view)
        await view.wait()

        if view.value is None:
            await interaction.followup.send(
                Lang.get_locale_string('common/interaction_timeout', interaction, description="Remove command"))
        elif view.value:
            try:
                await self.do_remove_command(interaction, trigger)
            except:
                raise CommandError("Failed to update custom command")
        else:
            await interaction.followup.send(Lang.get_locale_string('custom_commands/not_updating_command', interaction))

    @config_group.command(name='edit')
    async def edit_command(self, interaction: Interaction, trigger: Range[str, 1, trigger_max_length], response: str) -> None:
        """Edit a custom command"""
        await interaction_response(interaction).defer()

        my_trigger, my_command = await self.match_trigger(interaction.guild, trigger)
        msg = (f"Are you sure you want to edit the command `{my_command.trigger}`? This current response will be lost:\n"
               f"```{trim_message(my_command.response, 1000)}```\n")
        view = ConfirmView(interaction.user)
        await interaction.followup.send(msg, view=view)
        await view.wait()

        if view.value is None:
            await interaction.followup.send(
                Lang.get_locale_string('common/interaction_timeout', interaction, description="Edit command"))
        elif view.value:
            try:
                await self.do_update(interaction.guild, my_command, trigger, response)
                await self.send_response(
                    interaction,
                    "YES",
                    'command_updated',
                    trigger=my_trigger,
                    followup=True)
            except:
                raise CommandError("Failed to update custom command")
        else:
            await interaction.followup.send(Lang.get_locale_string('custom_commands/not_updating_command', interaction))

    @config_group.command(name='permission')
    async def set_command_permission(
            self,
            interaction: Interaction,
            trigger: Range[str, 1, trigger_max_length],
            value: Literal["Member", "Moderator"]) -> None:
        """Set permission level for a custom command"""
        # TODO: better permission scheme
        if value == "Member":
            permission = 0
        elif value == "Moderator":
            permission = 1
        else:
            permission = 0

        my_trigger, my_command = await self.match_trigger(interaction.guild, trigger)
        my_command.elevated = permission
        await my_command.save()
        await self.send_response(interaction, 'YES', 'command_updated', trigger=my_trigger)

    @config_group.command(name='setflag')
    async def set_command_flag(
            self,
            interaction: Interaction,
            trigger: Range[str, 1, trigger_max_length],
            flag: Literal["delete", "reply", "autocomplete", "ephemeral"],
            value: Literal["On", "Off"]) -> None:
        """Set/unset a flag for a custom command"""
        value = True if value == "On" else False
        await self.do_set_flag(interaction, trigger, flag, value)

    @config_group.command(name='setcontext', description="Restrict a command to a context")
    @app_commands.describe(
        trigger="The command trigger",
        context='The allowed context for this command')
    @app_commands.choices(context=[
        Choice(name='All', value=CustomCommandContext.all.value),
        Choice(name='Chat Command', value=CustomCommandContext.chat.value),
        Choice(name='App Command', value=CustomCommandContext.app.value),
    ])
    async def set_command_context(
            self,
            interaction: Interaction,
            trigger: Range[str, 1, trigger_max_length],
            context: Choice[int]) -> None:
        """Set the allowed context for a custom command"""
        guild_commands = self.commands[interaction.guild.id]
        if trigger in guild_commands:
            my_command = guild_commands[trigger]
            if my_command.allowedcontext == context.value:
                await interaction_response(interaction).send_message(
                    f"Command `{trigger}` is already limited to `{context.name}` contexts. *No change made.*",
                    ephemeral=True)
                return
            my_command.allowedcontext = context.value
            try:
                await my_command.save()
            except IntegrityError as e:
                Logging.info(f"Failed to update custom command: {e}", exc_info=True)
                raise CommandError("Failed to update custom command")
            await interaction_response(interaction).send_message(
                f"Command `{trigger}` can now be used in `{context.name}` contexts",
                ephemeral=False)
        else:
            await interaction_response(interaction).send_message(
                f"I don't know about that command",
                ephemeral=True)


    @do_command.autocomplete('topic')
    @edit_command.autocomplete('trigger')
    @remove_command.autocomplete('trigger')
    @set_command_flag.autocomplete('trigger')
    @set_command_context.autocomplete('trigger')
    async def trigger_autocomplete(
            self,
            interaction: discord.Interaction,
            current: str) -> list[app_commands.Choice[str]]:

        if interaction.guild is None:
            raise AppCommandError("Command must be used in a server")

        def can_autocomplete(command) -> bool:
            nonlocal interaction
            # Mods can see all commands
            if interaction.permissions.ban_members:
                return True
            # Members can only see commands in allowed contexts
            if command.allowedcontext not in [CustomCommandContext.all, CustomCommandContext.app]:
                return False
            # and only when autocomplete is enabled
            return command.autocomplete

        guild_commands = self.commands[interaction.guild.id]
        autocomplete_commands = [key for key, command in guild_commands.items() if can_autocomplete(command)]

        # generator for all command names:
        all_matching_commands = (i for i in autocomplete_commands if current.lower() in i.lower())
        # islice to limit to 25 options (discord API limit)
        some_commands = list(islice(all_matching_commands, 25))
        # convert matched list into list of choices
        ret = [app_commands.Choice(name=c, value=c) for c in some_commands]
        return ret

    ####################
    # chat commands
    ####################

    @commands.group(name="commands", aliases=['command'])
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def custom_command(self, ctx: commands.Context):
        """Show a list of custom commands"""
        if ctx.invoked_subcommand is None:
            await self.send_command_list(ctx)

    @custom_command.command(aliases=[
        "set_delete",
        "unset_delete",
        "set_reply",
        "unset_reply",
        "set_autocomplete",
        "unset_autocomplete",
        "set_ephemeral",
        "unset_ephemeral",])
    @commands.guild_only()
    async def command_flag(self, ctx: commands.Context, trigger: str):
        """
        Command must be invoked with one of the aliases:

        set_delete, unset_delete, set_reply, unset_reply

        Sets and unsets the respective command flags based on alias used.
        """
        if ctx.invoked_with not in ctx.command.aliases:
            await ctx.send_help(ctx.command)
            return

        trigger = trigger.lower()
        trigger = await Utils.clean(trigger)
        flag_val = False

        flag = re.sub("(un)?set_", "", ctx.invoked_with)

        # Coerce flag based on command alias
        if ctx.invoked_with.startswith('unset'):
            flag_val = False

        if ctx.invoked_with.startswith('set'):
            flag_val = True

        await self.do_set_flag(ctx, trigger, flag, flag_val)

    @custom_command.command(aliases=["new", "add"])
    @commands.guild_only()
    async def create(self, ctx: commands.Context, trigger: str, *, response: str ) -> None:
        """
        Create a custom command.

        Parameters
        ----------
        ctx
        trigger
            The command name to be used in chat
        response
            The response to this command

        Returns
        -------
        None

        """
        if len(trigger) > CustCommands.trigger_max_length:
            await self.send_response(ctx, "WHAT", 'trigger_too_long')
            return

        trigger = trigger.lower()
        cleaned_trigger = await Utils.clean(trigger)
        command = await CustomCommand.get_or_none(serverid=ctx.guild.id, trigger=cleaned_trigger)
        if command is None:
            if await self.do_create(ctx.guild, trigger, response):
                await self.send_response(ctx, "YES", 'command_added', trigger=trigger)
                return
            else:
                raise CommandError("Failed to create custom command")

        async def yes():
            try:
                cmd = self.bot.get_command("commands update")
                Logging.info(f"Updating custom command: {trigger}")
                await cmd(ctx, trigger, response=response)
                Logging.info(f"Updated custom command: {trigger} to {response}")
            except Exception as e:
                Logging.info(f"problem updating custom command: {trigger} to {response} - {e}")
                raise CommandError("Failed to update")

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

    @custom_command.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, trigger: str) -> None:
        """
        Remove a custom command

        Parameters
        ----------
        ctx
        trigger
            Command trigger

        Returns
        -------
        None
        """
        await self.do_remove_command(ctx, trigger)

    @custom_command.command(aliases=["edit", "set"])
    @commands.guild_only()
    async def update(self, ctx: commands.Context, trigger: str, *, response: str) -> None:
        """
        Edit an existing custom command

        Parameters
        ----------
        ctx
        trigger
            Command trigger
        response
            The new response

        Returns
        -------
        None
        """
        try:
            my_trigger, my_command = await self.match_trigger(ctx.guild, trigger)
        except KeyError:
            my_trigger = await Utils.clean(trigger.lower())
            if await self.do_create(ctx.guild, my_trigger, response):
                await self.send_response(ctx, 'WARNING', 'creating_command', trigger=trigger)
                return
            else:
                raise CommandError("Failed to create custom command")
        else:
            try:
                await self.do_update(ctx.guild, my_command, my_trigger, response)
                await self.send_response(ctx, "YES", 'command_updated', trigger=my_trigger)
            except:
                raise CommandError("Failed to update custom command")

    ####################
    # command internals
    ####################

    async def do_update(
            self,
            guild,
            command: CustomCommand,
            trigger: str,
            response: str) -> bool:
        try:
            command.response = response
            await command.save()
            self.commands[guild.id][trigger] = command
            return True
        except Exception as e:
            Logging.error(f"Failed to update custom command. {trigger} : {response} - {e}")
            raise e

    async def do_create(self, guild: Guild, trigger: str, response: str) -> bool:
        try:
            command = await CustomCommand.create(serverid=guild.id, trigger=trigger, response=response)
            self.commands[guild.id][trigger] = command
            return True
        except Exception as e:
            Logging.error(f"Failed to create custom command: {trigger} - {response} - {e}")
            return False

    async def send_command_list(self, ctx: Union[Context, Interaction]):
        embed = discord.Embed(
            color=0x663399,
            title=Lang.get_locale_string("custom_commands/list_commands", ctx, server_name=ctx.guild.name))

        value = ""
        sender = Sender(ctx)
        if len(self.commands[ctx.guild.id].keys()) > 0:
            for trigger in self.commands[ctx.guild.id].keys():
                this_command: CustomCommand = self.commands[ctx.guild.id][trigger]

                context_icon = '⛔️'
                if this_command.allowedcontext == CustomCommandContext.all:
                    context_icon = '🌍'
                elif this_command.allowedcontext == CustomCommandContext.chat:
                    context_icon = '💬'
                elif this_command.allowedcontext == CustomCommandContext.app:
                    context_icon = '📱'

                new_entry = trigger
                flag_str = ""
                flag_str += f"{'👻' if this_command.deletetrigger else ''}"
                flag_str += f"{'⤴️' if this_command.reply else ''}"
                flag_str += f"{'👁️' if this_command.autocomplete else ''}"
                flag_str += f"{'🫥' if this_command.ephemeral else ''}"
                flag_str = f"`{context_icon}{flag_str}`" if flag_str else ''
                new_entry = f"{new_entry} {flag_str}"

                if len(value) + len(new_entry) > 1000:
                    embed.add_field(name="\u200b", value=value)
                    value = ""
                value += new_entry
                value += "\n"
            embed.add_field(name="\u200b", value=value)

            fields_description = [
                'delete trigger: `👻`',
                'reply: `⤴️`',
                'autocomplete: `👁`',
                'ephemeral: `🫥`',
                'context: /📱 !💬 *🌍'
            ]
            embed.add_field(name="__**Flags**__", value="\n".join(fields_description), inline=False)

            await sender.send(embed=embed)
        else:
            await sender.send(Lang.get_locale_string("custom_commands/no_commands", ctx))

    async def do_set_flag(self, ctx: Union[Context, Interaction], trigger: str, flag: str, flag_val: bool) -> None:
        Logging.info(f"Setting flag {flag} to {flag_val} for trigger `{trigger}`")
        if len(trigger) > CustCommands.trigger_max_length:
            emoji = 'WHAT'
            lang_key = 'trigger_too_long'
            tokens = dict()
        elif trigger in self.commands[ctx.guild.id]:
            try:
                if flag == "delete":
                    flag = "deletetrigger"
                if hasattr(self.commands[ctx.guild.id][trigger], flag):
                    setattr(self.commands[ctx.guild.id][trigger], flag, flag_val)
                    await self.commands[ctx.guild.id][trigger].save()
            except Exception as e:
                await Utils.handle_exception("Custom Commands set flag exception", e)
                raise commands.CommandError("Custom Commands set flag exception")

            emoji = 'YES'
            lang_key = f'{flag}_trigger_updated'
            tokens = dict(trigger=trigger, value='ON' if flag_val else 'OFF')
        else:
            emoji = 'NO'
            lang_key = 'not_found'
            tokens = dict(trigger=trigger)
        await self.send_response(ctx, emoji, lang_key, **tokens)

    async def do_remove_command(self, ctx: Union[Context, Interaction], trigger: str):
        tokens = dict()
        try:
            my_trigger, my_command = await self.match_trigger(ctx.guild, trigger)
            await my_command.delete()
            del self.commands[ctx.guild.id][my_trigger]
            emoji = 'YES'
            lang_key = 'command_removed'
            tokens = dict(trigger=trigger)
        except ValueError:
            emoji = 'WHAT'
            lang_key = 'trigger_too_long'
        except KeyError:
            emoji = 'NO'
            lang_key = 'not_found'
            tokens = dict(trigger=trigger)
        await self.send_response(ctx, emoji, lang_key, **tokens)

    async def match_trigger(self, guild, trigger: str) -> tuple[str, CustomCommand]:
        cleaned_trigger = await Utils.clean(trigger.lower())

        if len(cleaned_trigger) > CustCommands.trigger_max_length:
            raise ValueError(f"Trigger `{cleaned_trigger}` is too long ({len(cleaned_trigger)})")
        elif cleaned_trigger in self.commands[guild.id]:
            return cleaned_trigger, self.commands[guild.id][cleaned_trigger]
        else:
            raise KeyError(f"Trigger `{cleaned_trigger}` not found")

    ####################
    # listeners
    ####################

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not hasattr(message.channel, "guild") or message.channel.guild is None:
            return
        if message.guild.id not in self.commands:
            return
        prefix = Configuration.get_var("bot_prefix")
        if message.content.startswith(prefix, 0):
            cleaned_message = await Utils.clean(message.content.lower())
            for trigger in self.commands[message.guild.id]:
                if cleaned_message == prefix+trigger or (cleaned_message.startswith(trigger, len(prefix)) and cleaned_message[len(prefix+trigger)] == " "):
                    command: CustomCommand = self.commands[message.guild.id][trigger]
                    reference = message if command.reply else None
                    command_content = command.response.replace("@", "@\u200b").format(author=message.author.mention)
                    if command.deletetrigger:
                        await message.delete()
                    await message.channel.send(command_content, reference=reference)


async def setup(bot):
    await bot.add_cog(CustCommands(bot))
