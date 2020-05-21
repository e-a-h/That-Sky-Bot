import json

import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Lang, Logging, Utils
from utils.Database import Guild, Localization


class LangConfig(BaseCog):
    unset_str = ["*", "x", "none", "unset", "off"]

    def __init__(self, bot):
        super().__init__(bot)

    @commands.guild_only()
    @commands.group(name="lang", invoke_without_command=True)
    async def lang(self, ctx):
        channels = []
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string('lang/lang_settings_title', ctx, server_name=ctx.guild.name))

        guild_row = Guild.get_or_none(serverid=ctx.guild.id)
        if guild_row:
            embed.add_field(name="Server default", value=guild_row.defaultlocale or "none")

        localization_rows = Localization.select().join(Guild).where(Guild.serverid == ctx.guild.id)
        for row in localization_rows:
            channels.append(self.bot.get_channel(row.channelid).mention)
            embed.add_field(name=f"#{self.bot.get_channel(row.channelid).name}",
                            value=row.locale,
                            inline=True)
        await ctx.send(embed=embed)

    # reload lang
    @commands.guild_only()
    @lang.command()
    async def reload(self, ctx):
        Lang.load_locales()
        await ctx.send(Lang.get_locale_string('lang/reloaded', ctx, server_name=ctx.guild.name))

    # Set default server lang
    @commands.guild_only()
    @lang.command(aliases=["server_locale", "serverlocale", "default"])
    async def set_server_locale(self, ctx, locale: str):
        if locale not in Lang.locales and locale not in self.unset_str:
            await ctx.send(Lang.get_locale_string('lang/unknown_locale', ctx, locale=locale, locale_lsit=Lang.locales))
            return

        if locale in self.unset_str:
            locale = ""
        guild_row = Guild.get_or_create(serverid=ctx.guild.id)[0]

        # Don't set/save if input arg is already default
        if locale == guild_row.defaultlocale:
            await ctx.send(
                Lang.get_locale_string('lang/default_not_changed', ctx, locale=locale, server_name=ctx.guild.name))
            return

        guild_row.defaultlocale = locale
        guild_row.save()
        await ctx.send(Lang.get_locale_string('lang/default_set', ctx, locale=locale, server_name=ctx.guild.name))

    # Set channel-specific locale
    @commands.guild_only()
    @lang.command(aliases=["channel", "channel_locale"])
    async def set_channel_locale(self, ctx, locale: str, channel_id: int = 0):
        if locale not in Lang.locales and locale not in self.unset_str:
            await ctx.send(Lang.get_locale_string('lang/unknown_locale', ctx, locale=locale, locale_lsit=Lang.locales))
            return

        # use input channel, or if input is 0, use channel from command context
        channel_id = ctx.channel.id if channel_id == 0 else channel_id

        guild_row = Guild.get_or_create(serverid=ctx.guild.id)[0]
        old_value = None

        localization_row = Localization.select().join(Guild).where(
            (Guild.serverid == ctx.guild.id) &
            (Localization.channelid == channel_id))

        if len(localization_row) == 1:
            localization_row = localization_row[0]
            old_value = localization_row.locale
        else:
            localization_row = None

        if locale in self.unset_str:
            if not localization_row:
                await ctx.send(Lang.get_locale_string('lang/channel_not_unset', ctx, channelid=channel_id))
            else:
                localization_row.delete_instance()
                await ctx.send(Lang.get_locale_string('lang/channel_unset', ctx, old_value=old_value))
            return

        if not localization_row:
            localization_row = Localization.create(guild=guild_row, channelid=channel_id)

        if localization_row.locale == locale:
            await ctx.send(Lang.get_locale_string('lang/channel_already_set', ctx, channelid=channel_id, locale=locale))
            return

        localization_row.locale = locale
        localization_row.save()
        await ctx.send(Lang.get_locale_string('lang/channel_set', ctx, channelid=channel_id, locale=locale))

    # get translation string get_translation(locale, key, **kwargs)
    @commands.guild_only()
    @lang.command(aliases=["test", "testkey", "test_key"])
    async def test_lang_key(self, ctx, lang_key: str, locale: str = '', *, json_args: str = ''):
        """
        Test a language key with localization

        ctx:
        lang_key:
        locale: name a locale to use, * for default (per server, channel), or "all" to show all localizations
        json_args: JSON-formatted string representing required tokens for the given key
        """
        try:
            arg_dict = json.loads(json_args)
        except Exception as ex:
            arg_dict = dict()

        if locale == '*':
            locale = ctx
        if locale.lower() in ['all', 'all_locales']:
            locale = Lang.ALL_LOCALES

        defaulted_locale = Lang.get_defaulted_locale(locale)
        try:
            result = Lang.get_locale_string(lang_key, locale, **arg_dict)
            await ctx.send(Lang.get_locale_string('lang/test',
                                                  ctx,
                                                  lang_key=lang_key,
                                                  locale=defaulted_locale,
                                                  result=result))
        except Exception as ex:
            await ctx.send(Lang.get_locale_string('lang/test_failed',
                                                  ctx,
                                                  lang_key=lang_key,
                                                  locale=defaulted_locale))

    # TODO: set/save translation string? set_translation(locale, key, value)

    # TODO: SET ALIAS FOR COMMAND TRANSLATION

    # TODO DB list of alias->(command,locale)

    @commands.guild_only()
    @commands.command()
    async def alt_invoke(self, ctx, lang_key: str, locale: str = '', *, json_args: str = ''):
        # invoke another
        pass

    # Command alias suffix if possible?


def setup(bot):
    bot.add_cog(LangConfig(bot))
