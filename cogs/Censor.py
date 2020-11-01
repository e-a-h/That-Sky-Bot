import asyncio
import re
from urllib import parse
from urllib.parse import urlparse

import discord
from discord import DMChannel
from discord.ext import commands, tasks
from discord.ext.commands import clean_content

from cogs.BaseCog import BaseCog
from utils import Utils
from utils.Utils import Configuration
from utils.Utils import INVITE_MATCHER, URL_MATCHER


class Censor(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.regexes = dict()
        self.log_channels = dict()
        bot.loop.create_task(self.startup_cleanup())

    async def startup_cleanup(self):
        if 'message_deletes' not in self.bot.data:
            self.bot.data['message_deletes'] = dict()

        for guild in self.bot.guilds:
            if guild.id not in self.bot.data['message_deletes']:
                self.bot.data['message_deletes'][guild.id] = dict()

            # TODO: put this into db?
            channel_id = self.get_censor_config(guild.id)["LOG_CHANNEL"]
            if channel_id:
                self.log_channels[guild.id] = self.bot.get_channel(channel_id)
            else:
                self.log_channels[guild.id] = self.bot.get_guild_log_channel(guild.id)

        # TODO: find out what the condition is we need to wait for instead of just sleep
        await asyncio.sleep(10)
        self.delete_messages.start()

    @tasks.loop(seconds=0.1)
    async def delete_messages(self):
        for guild_id, deletes in self.bot.data['message_deletes'].items():
            guild = self.bot.get_guild(guild_id)
            if guild:
                for channel_id, message_id in deletes.items():
                    try:
                        channel = self.bot.get_channel(channel_id)
                        # channel = await self.bot.fetch_channel(channel_id)
                        message = await channel.fetch_message(message_id)
                        await message.delete()
                        print(f"censor deleted message {message_id}")
                    except (discord.NotFound, discord.HTTPException, discord.Forbidden) as e:
                        print(f"message not found or missing permission. removing {message_id} from delete list")
                        chan_delete_dict = dict(self.bot.data['message_deletes'][guild_id][channel_id])
                        del chan_delete_dict[message_id]

    def cog_unload(self):
        self.delete_messages.cancel()

    async def censor_log(self, guild_id, key, message, clean_message=None, sequence=None):
        if key == '_word':
            # word matching
            pass
        elif key == '_domain_blocked':
            # domain matching
            pass
        else:
            # token matching
            pass

        if key.startswith("censor_message_failed"):
            pass

        channel = message.channel.mention
        author_log = Utils.get_member_log_name(message.author)

        try:
            await self.log_channels[guild_id].send(f"""
                `{sequence}` by {author_log} was censored in {channel}
                ```{clean_message}```
            """)
        except Exception as e:
            # failed to log
            pass

    async def describe_list(self, ctx, the_list):

        pass

    def get_censor_config(self, guild_id):
        return Configuration.MASTER_CONFIG['GUILD_CENSORS'][str(guild_id)]

    @commands.group(name="configure", aliases=["cfg", "config"], invoke_without_command=True)
    @commands.guild_only()
    async def configure(self, ctx):
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @configure.group(name="censor_list", invoke_without_command=True)
    @commands.guild_only()
    async def censor_list(self, ctx):
        await ctx.send("censor_list group")

    @configure.group(name="censor_word_list", invoke_without_command=True)
    @commands.guild_only()
    async def censor_word_list(self, ctx):
        await ctx.send("censor_word_list group")

    @censor_list.command(name="list")
    @commands.guild_only()
    async def token_list(self, ctx):
        await ctx.send("censor_list list")

    @censor_list.command(name="add")
    @commands.guild_only()
    async def token_add(self, ctx, token: str):
        token_list = self.get_censor_config(ctx.guild.id)['TOKEN_CENSOR_LIST']
        if not isinstance(token_list, list):
            token_list = []
        if token not in token_list:
            token_list.append(token)
            Configuration.save()
            await ctx.send(f"token '{token}' added to token censor list (partial word matching)")

    @censor_list.command(name="remove")
    @commands.guild_only()
    async def token_remove(self, ctx):
        await ctx.send("censor_list remove")

    @censor_word_list.command(name="list")
    @commands.guild_only()
    async def word_list(self, ctx):
        await ctx.send("censor_word_list list")

    @censor_word_list.command(name="add")
    @commands.guild_only()
    async def word_add(self, ctx):
        await ctx.send("censor_word_list add")

    @censor_word_list.command(name="remove")
    @commands.guild_only()
    async def word_remove(self, ctx):
        await ctx.send("censor_word_list remove")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # TODO: put this into db?
        if message.channel is None or \
                isinstance(message.channel, DMChannel) or \
                not self.get_censor_config(message.channel.guild.id)["ENABLED"] or \
                self.bot.user.id == message.author.id:
            return
        await self.check_message(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, event: discord.RawMessageUpdateEvent):
        channel = self.bot.get_channel(int(event.data["channel_id"]))
        if channel is None or \
                isinstance(channel, DMChannel) or \
                not self.get_censor_config(channel.guild.id)["ENABLED"]:
            return
        permissions = channel.permissions_for(channel.guild.me)
        if permissions.read_messages and permissions.read_message_history:
            try:
                message = await channel.fetch_message(event.message_id)
            except (discord.NotFound, discord.Forbidden): # we should never get forbidden, be we do, somehow
                pass
            else:
                if self.bot.user.id != message.author.id:
                    await self.check_message(message)

    async def check_message(self, message: discord.Message):
        if message.guild is None or \
                message.webhook_id is not None or \
                message.author == message.guild.me:
            return
        ctx = await self.bot.get_context(message)
        if ctx.author.guild_permissions.mute_members:
            # Ignore anyone with mute power
            # TODO: better permissions
            #return
            pass
        # TODO: put all this into db?
        guild_censors = self.get_censor_config(message.channel.guild.id)
        censor_list = guild_censors["TOKEN_CENSOR_LIST"]
        word_censor_list = guild_censors["WORD_CENSOR_LIST"]
        guilds = guild_censors["ALLOWED_INVITE_LIST"]
        domain_list = guild_censors["DOMAIN_LIST"]
        domains_allowed = guild_censors["DOMAIN_LIST_ALLOWED"]
        content = message.content.replace('\\', '')
        decoded_content = parse.unquote(content)
        censored = False
        if len(guilds) != 0:
            codes = INVITE_MATCHER.findall(decoded_content)
            for code in codes:
                try:
                    invite: discord.Invite = await self.bot.fetch_invite(code)
                except discord.NotFound:
                    await self.censor_invite(ctx, code, "INVALID INVITE")
                    return
                if invite.guild is None:
                    await self.censor_invite(ctx, code, "DM group")
                    censored = True
                else:
                    if invite.guild.id not in guilds and invite.guild.id != message.guild.id:
                        await self.censor_invite(ctx, code, invite.guild.name)
                        censored = True

        if not censored:
            content = content.lower()
            for bad in (w.lower() for w in censor_list):
                if bad in content:
                    await self.censor_message(message, bad)
                    censored = True
                    break

        if not censored and len(word_censor_list) > 0:
            if ctx.guild.id not in self.regexes:
                regex = re.compile(r"\b(" + '|'.join(re.escape(word) for word in word_censor_list) + r")\b", re.IGNORECASE)
                self.regexes[ctx.guild.id] = regex
            else:
                regex = self.regexes[ctx.guild.id]
            match = regex.findall(message.content)
            if len(match):
                await self.censor_message(message, match[0], "_word")
                censored = True

        if not censored and len(domain_list) > 0:
            link_list = URL_MATCHER.findall(message.content)
            for link in link_list:
                url = urlparse(link)
                domain = url.hostname
                if (domain in domain_list) is not domains_allowed:
                    await self.censor_message(message, url.hostname, "_domain_blocked")
                print(domain)

    async def censor_message(self, message, bad, key=""):
        if message.channel.permissions_for(message.guild.me).manage_messages:
            try:
                self.bot.data["message_deletes"][message.guild.id][message.channel.id] = message.id
                print(f"censor message is {message.id}")
            except discord.NotFound as ex:
                pass
            else:
                clean_message = await Utils.clean(message.content, message.guild, markdown=False)
                await self.censor_log(message.guild.id,
                                      f'censored_message{key}',
                                      message,
                                      clean_message=clean_message,
                                      sequence=bad)
                # self.bot.dispatch("user_censored", message)
        else:

            clean_message = await Utils.clean(message.content, message.guild, markdown=False)
            await self.censor_log(message.guild.id,
                                  f'censor_message_failed{key}',
                                  message,
                                  clean_message=clean_message,
                                  sequence=bad)
            # self.bot.dispatch("user_censored", message)

    async def censor_invite(self, ctx, code, server_name):
        is_trusted = ctx.author.guild_permissions.ban_members
        # Allow for users with a trusted role, or trusted users, to post invite links
        guild_censors = self.get_censor_config(ctx.guild.id)
        if 'ALLOW_TRUSTED_BYPASS' in guild_censors and guild_censors['ALLOW_TRUSTED_BYPASS'] and is_trusted:
            return

        ctx.bot.data["message_deletes"].add(ctx.message.id)
        print(f"censor invite {ctx.message.id}")
        clean_message = await clean_content().convert(ctx, ctx.message.content)
        try:
            await ctx.message.delete()
            await self.censor_log(ctx.message.guild.id,
                                  'censored_invite',
                                  ctx.message,
                                  clean_message=clean_message,
                                  sequence=f"invite code {code} for server '{server_name}'")
            # GearbotLogging.log_key(ctx.guild.id, 'censored_invite', user=clean_name, code=code, message=clean_message,
            #                        server_name=server_name, user_id=ctx.message.author.id,
            #                        channel=ctx.message.channel.mention)
        except discord.NotFound:
            # we failed? guess we lost the race, log anyways
            await self.censor_log(ctx.message.guild.id,
                                  'invite_censor_fail',
                                  ctx.message,
                                  clean_message=clean_message,
                                  sequence=f"~~invite code {code} for server '{server_name}'~~")
            # TODO: better failure logging
            # GearbotLogging.log_key(ctx.guild.id, 'invite_censor_fail', user=clean_name, code=code,
            #                        message=clean_message, server_name=server_name, user_id=ctx.message.author.id,
            #                        channel=ctx.message.channel.mention)
            if ctx.message.id in ctx.bot.data["message_deletes"]:
                ctx.bot.data["message_deletes"].remove(ctx.message.id)
                print("failed censor invite?")
        except discord.Forbidden:
            await self.censor_log(ctx.message.guild.id,
                                  'invite_censor_forbidden',
                                  ctx.message,
                                  clean_message=clean_message,
                                  sequence=f"~~invite code {code} for server '{server_name}'~~")
            # TODO: better failure logging
            if ctx.message.id in ctx.bot.data["message_deletes"]:
                ctx.bot.data["message_deletes"].remove(ctx.message.id)
                print("no permission to remove message")
        self.bot.dispatch("user_censored", ctx.message)


def setup(bot):
    bot.add_cog(Censor(bot))