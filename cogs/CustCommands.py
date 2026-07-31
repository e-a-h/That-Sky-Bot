import asyncio
import re
from itertools import islice
from typing import Any, Union, Literal, Optional, Dict

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
    """Discord cog for managing guild-specific custom commands.

    Custom commands are stored in the database and cached per guild by trigger.
    The cog exposes both app-command and prefix-command configuration flows for
    listing, creating, editing, removing, and flagging commands. It also serves
    configured responses when users invoke a trigger through `/enlighten` or the
    bot prefix.

    Command flags control whether the trigger message is deleted, whether the
    response replies to the trigger, whether app-command autocomplete includes
    the trigger, whether the response is ephemeral, and which invocation contexts
    are allowed.
    """

    trigger_max_length: int = 20
    max_autocomplete_results: int = 25

    def __init__(self, bot):
        super().__init__(bot)
        self.commands: Dict[int, Dict[str, CustomCommand]] = {}

    async def cog_check(self, ctx):
        Logging.info(f"{self.__class__.__name__} cog check")
        can_ban = isinstance(ctx.author, discord.Member) and ctx.channel.permissions_for(ctx.author).ban_members
        allowed = (ctx.guild and can_ban) or await Utils.permission_manage_bot(ctx)
        return bool(allowed)

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
        self.commands[guild.id] = {}
        for command in await CustomCommand.filter(serverid=guild.id):
            self.commands[guild.id][command.trigger] = command

    @staticmethod
    async def send_response(ctx: Union[Context, Interaction], emoji_name, lang_key, **kwargs):
        if 'trigger' in kwargs:
            kwargs['trigger'] = kwargs['trigger'].encode('utf-8').decode('unicode-escape')

        msg = Lang.get_locale_string(f'custom_commands/{lang_key}', ctx, **kwargs)
        emoji = Emoji.get_chat_emoji(emoji_name)
        if isinstance(ctx, Interaction) and 'followup' in kwargs and kwargs['followup']:
            ephemeral = 'ephemeral' in kwargs and kwargs['ephemeral']
            await ctx.followup.send(f'{emoji} {msg}', ephemeral=ephemeral)
        else:
            sender = Sender(ctx)
            await sender.send(f"{emoji} {msg}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.commands[guild.id] = {}

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.commands[guild.id]
        await CustomCommand.filter(serverid=guild.id).delete()

    ####################
    # app commands
    ####################

    @app_commands.guild_only()
    @app_commands.command(name='enlighten')
    async def do_command(self, interaction: Interaction, topic: Range[str, 1, trigger_max_length], to: Optional[User] = None) -> None:
        """
        Perform a custom command

        Parameters
        ----------
        interaction
        topic
            green friends in a pod
        to
            Ping someone. Choose yourself for a private response.

        Returns
        -------
        None
        """
        # cleaned_topic = await Utils.clean(topic)
        if interaction.guild is None:
            return
        for trigger in self.commands[interaction.guild.id]:
            if topic == trigger:
                command: CustomCommand = self.commands[interaction.guild.id][trigger]
                if command.allowedcontext not in [CustomCommandContext.all, CustomCommandContext.app]:
                    await interaction_response(interaction).send_message(
                        f"The command `{command.trigger}` may only be used in "
                        f"`chat command` contexts\n"
                        f"(hint, try typing `{Configuration.get_var('bot_prefix')}{trigger}`)",
                        ephemeral=True)
                    return
                if command.elevated > 0:
                    # TODO: map elevated value to permission level
                    # for now, greater than zero means "moderator"
                    if not interaction.permissions.ban_members:
                        raise MissingPermissions([""])
                command_content = command.response.replace("@", "@\u200b").format(author=interaction.user.mention)
                ephemeral = command.ephemeral or to is not None and to.id == interaction.user.id

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
        guild = interaction.guild
        assert isinstance(guild, Guild)  # Guild type is assured by the guild_only decorator of config_group

        await interaction_response(interaction).defer()
        cleaned_trigger = await Utils.clean(trigger.lower())
        command = await CustomCommand.get_or_none(serverid=guild.id, trigger=cleaned_trigger)

        if command is None:
            if await self.do_create(guild, cleaned_trigger, response):
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
                await self.do_update(guild, command, cleaned_trigger, response)
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
        guild = interaction.guild
        assert isinstance(guild, Guild)  # Guild type is assured by the guild_only decorator of config_group

        await interaction_response(interaction).defer(ephemeral=True)

        my_trigger, my_command = await self.match_trigger(guild, trigger)
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
        guild = interaction.guild
        assert isinstance(guild, Guild)  # Guild type is assured by the guild_only decorator of config_group

        await interaction_response(interaction).defer()

        my_trigger, my_command = await self.match_trigger(guild, trigger)
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
                await self.do_update(guild, my_command, trigger, response)
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
        guild = interaction.guild
        assert isinstance(guild, Guild)  # Guild type is assured by the guild_only decorator of config_group

        # TODO: better permission scheme
        if value == "Member":
            permission = 0
        elif value == "Moderator":
            permission = 1
        else:
            permission = 0

        my_trigger, my_command = await self.match_trigger(guild, trigger)
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
        my_value = True if value == "On" else False
        await self.do_set_flag(interaction, trigger, flag, my_value)

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
        guild = interaction.guild
        assert isinstance(guild, Guild)  # Guild type is assured by the guild_only decorator of config_group

        guild_commands = self.commands[guild.id]
        if trigger in guild_commands:
            my_command = guild_commands[trigger]
            if my_command.allowedcontext == context.value:
                await interaction_response(interaction).send_message(
                    f"Command `{trigger}` is already limited to `{context.name}` contexts. *No change made.*",
                    ephemeral=True)
                return
            my_value = CustomCommandContext(context.value)
            my_command.allowedcontext = my_value
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


    # set_command_context causes inspection to fail here.
    # if `describe` and `choices` decorators are removed from that function, it works. :(
    # noinspection PyUnresolvedReferences
    @do_command.autocomplete('topic')
    @edit_command.autocomplete('trigger')
    @remove_command.autocomplete('trigger')
    @set_command_flag.autocomplete('trigger')
    @set_command_context.autocomplete('trigger')
    async def trigger_autocomplete(
            self,
            interaction: discord.Interaction,
            current: str) -> list[app_commands.Choice]:

        Logging.debug(f"Autocomplete called with: {current}")

        if interaction.guild is None:
            raise AppCommandError("Command must be used in a server")

        def can_autocomplete(command) -> bool:
            nonlocal interaction
            # Mods can see all commands
            if interaction.permissions.ban_members:
                return True
            # Members can only see commands in allowed contexts
            if command.allowedcontext not in [CustomCommandContext.all.value, CustomCommandContext.app.value]:
                return False
            # and only when autocomplete is enabled
            return command.autocomplete

        guild_commands = self.commands[interaction.guild.id]
        autocomplete_commands = [key for key, command in guild_commands.items() if can_autocomplete(command)]
        # Logging.debug(f"Autocomplete commands: {autocomplete_commands}")

        Logging.debug(f"Autocomplete commands: {autocomplete_commands}")

        # generator for all command names:
        all_matching_commands = (i for i in autocomplete_commands if current.lower() in i.lower())
        # islice to limit to 25 options (discord API limit)
        Logging.debug(f"Autocomplete matching commands: {all_matching_commands}")

        some_commands = list(islice(all_matching_commands, CustCommands.max_autocomplete_results))
        # convert matched list into list of choices
        ret = [app_commands.Choice(name=c, value=c) for c in some_commands]
        Logging.debug(f"Autocomplete results: {ret}")
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
        if not ctx.command or str(ctx.invoked_with) not in ctx.command.aliases:
            await ctx.send_help(ctx.command)
            return

        trigger = trigger.lower()
        trigger = await Utils.clean(trigger)
        flag_val = False

        inv = str(ctx.invoked_with)
        flag = re.sub("(un)?set_", "", inv)

        # Coerce flag based on command alias
        if inv.startswith('unset'):
            flag_val = False

        if inv.startswith('set'):
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
        guild = ctx.guild
        assert isinstance(guild, Guild)  # Guild type is assumed (invoking commands are guild-only)

        if len(trigger) > CustCommands.trigger_max_length:
            await self.send_response(ctx, "WHAT", 'trigger_too_long')
            return

        trigger = trigger.lower()
        cleaned_trigger = await Utils.clean(trigger)

        command = await CustomCommand.get_or_none(serverid=guild.id, trigger=cleaned_trigger)
        if command is None:
            if await self.do_create(guild, trigger, response):
                await self.send_response(ctx, "YES", 'command_added', trigger=trigger)
                return
            raise CommandError("Failed to create custom command")

        async def yes():
            nonlocal ctx, trigger, response
            try:
                cmd = self.bot.get_command("commands update")
                if cmd is None:
                    raise CommandError("Failed to find command update command")
                Logging.info(f"Updating custom command: {trigger}")
                await cmd(ctx, trigger, response=response)
                Logging.info(f"Updated custom command: {trigger} to {response}")
            except Exception as e:
                Logging.info(f"problem updating custom command: {trigger} to {response} - {e}")
                raise CommandError("Failed to update") from e

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
        guild = ctx.guild
        assert isinstance(guild, Guild)  # Guild type is assumed (invoking commands are guild-only)

        try:
            my_trigger, my_command = await self.match_trigger(guild, trigger)
        except KeyError:
            my_trigger = await Utils.clean(trigger.lower())
            if await self.do_create(guild, my_trigger, response):
                await self.send_response(ctx, 'WARNING', 'creating_command', trigger=trigger)
                return
            else:
                raise CommandError("Failed to create custom command")
        else:
            try:
                await self.do_update(guild, my_command, my_trigger, response)
                await self.send_response(ctx, "YES", 'command_updated', trigger=my_trigger)
            except:
                raise CommandError("Failed to update custom command")

    ####################
    # command internals
    ####################

    async def do_update(
            self,
            guild: Guild,
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
        guild = ctx.guild
        assert isinstance(guild, Guild)  # Guild type is assumed (invoking commands are guild-only)

        # Force reload from database
        await self.init_guild(guild)

        sender = Sender(ctx)
        if len(self.commands[guild.id].keys()) == 0:
            # No commands, send a message instead of command list
            await sender.send(Lang.get_locale_string("custom_commands/no_commands", ctx))
            return

        embed = discord.Embed(
            color=0x663399,
            title=Lang.get_locale_string("custom_commands/list_commands", ctx, server_name=guild.name))

        command_list = {
            CustomCommandContext.all: [],
            CustomCommandContext.chat: [],
            CustomCommandContext.app: [],
            'unknown': []
        }

        for trigger in self.commands[guild.id].keys():
            this_command: CustomCommand = self.commands[guild.id][trigger]

            new_entry = trigger
            flag_str = ""
            flag_str += f"{'👻' if this_command.deletetrigger else ''}"
            flag_str += f"{'⤴️' if this_command.reply else ''}"
            flag_str += f"{'👁️' if this_command.autocomplete else ''}"
            flag_str += f"{'🫥' if this_command.ephemeral else ''}"
            flag_str = f"`{flag_str}`" if flag_str else ""
            new_entry = f"{new_entry} {flag_str}"
            if this_command.allowedcontext in command_list:
                command_list[this_command.allowedcontext].append(new_entry)
            else:
                command_list['unknown'].append(new_entry)

        def populate_list(my_list, list_name):
            value = ""
            for entry in my_list:
                if len(value) + len(entry) > 1000:
                    embed.add_field(name=list_name or "\u200b", value=value)
                    value = ""
                value += entry
                value += "\n"
            embed.add_field(name=list_name or "\u200b", value=value)

        if command_list[CustomCommandContext.all]:
            command_list[CustomCommandContext.all].sort()
            populate_list(command_list[CustomCommandContext.all], "__Global Commands__")
        if command_list[CustomCommandContext.chat]:
            command_list[CustomCommandContext.chat].sort()
            populate_list(command_list[CustomCommandContext.chat], "__Chat-only Commands__")
        if command_list[CustomCommandContext.app]:
            command_list[CustomCommandContext.app].sort()
            populate_list(command_list[CustomCommandContext.app], "__App-only Commands__")
        if command_list['unknown']:
            populate_list(command_list['unknown'], "__Unknown Contexts__")

        fields_description = [
            'delete trigger: `👻`',
            'reply: `⤴️`',
            'autocomplete: `👁`',
            'ephemeral: `🫥`'
        ]
        embed.add_field(name="__**Flags**__", value="\n".join(fields_description), inline=False)
        await sender.send(embed=embed)

    async def do_set_flag(self, ctx: Union[Context, Interaction], trigger: str, flag: str, flag_val: bool) -> None:
        guild = ctx.guild
        assert isinstance(guild, Guild)  # Guild type is assumed (invoking commands are guild-only)

        Logging.info(f"Setting flag {flag} to {flag_val} for trigger `{trigger}`")
        if len(trigger) > CustCommands.trigger_max_length:
            emoji = 'WHAT'
            lang_key = 'trigger_too_long'
            tokens = {}
        elif trigger in self.commands[guild.id]:
            try:
                if flag == "delete":
                    flag = "deletetrigger"
                if hasattr(self.commands[guild.id][trigger], flag):
                    setattr(self.commands[guild.id][trigger], flag, flag_val)
                    await self.commands[guild.id][trigger].save()
            except Exception as e:
                await Utils.handle_exception("Custom Commands set flag exception", e)
                raise commands.CommandError("Custom Commands set flag exception")

            emoji = 'YES'
            lang_key = f'{flag}_trigger_updated'
            tokens = dict(trigger=trigger, value='ON' if flag_val else 'OFF')
        else:
            emoji = 'NO'
            lang_key = 'not_found'
            tokens = {"trigger": trigger}
        await self.send_response(ctx, emoji, lang_key, **tokens)

    async def do_remove_command(self, ctx: Union[Context, Interaction], trigger: str):
        guild = ctx.guild
        assert isinstance(guild, Guild)  # Guild type is assumed (invoking commands are guild-only)

        tokens = {}
        try:
            my_trigger, my_command = await self.match_trigger(guild, trigger)
            await my_command.delete()
            del self.commands[guild.id][my_trigger]
            emoji = 'YES'
            lang_key = 'command_removed'
            tokens = {"trigger": trigger}
        except ValueError:
            emoji = 'WHAT'
            lang_key = 'trigger_too_long'
        except KeyError:
            emoji = 'NO'
            lang_key = 'not_found'
            tokens = {"trigger": trigger}
        await self.send_response(ctx, emoji, lang_key, **tokens)

    async def match_trigger(self, guild, trigger: str) -> tuple[str, CustomCommand]:
        cleaned_trigger = await Utils.clean(trigger.lower())

        if len(cleaned_trigger) > CustCommands.trigger_max_length:
            raise ValueError(f"Trigger `{cleaned_trigger}` is too long ({len(cleaned_trigger)})")

        if cleaned_trigger in self.commands[guild.id]:
            return cleaned_trigger, self.commands[guild.id][cleaned_trigger]
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

        guild = message.channel.guild
        assert isinstance(guild, Guild)  # Guild type is enforced above

        if not hasattr(message.guild, "id") or guild.id not in self.commands:
            return

        prefix = Configuration.get_var("bot_prefix")
        if message.content.startswith(prefix, 0):
            cleaned_message = await Utils.clean(message.content.lower())
            for trigger in self.commands[guild.id]:
                if (cleaned_message == prefix+trigger or
                        (cleaned_message.startswith(trigger, len(prefix)) and
                         cleaned_message[len(prefix+trigger)] == " ")):
                    command: CustomCommand = self.commands[guild.id][trigger]
                    command_content = command.response.replace("@", "@\u200b").format(author=message.author.mention)
                    if command.deletetrigger:
                        await message.delete()
                    my_args: dict[str, Any] = { "content": command_content }
                    if command.reply:
                        my_args["reference"] = message
                    await message.channel.send(**my_args)


async def setup(bot):
    await bot.add_cog(CustCommands(bot))
