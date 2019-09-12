import time
from datetime import datetime

import sentry_sdk
from discord.ext.commands import Bot
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import ConnectionClosed, Embed, Colour

from utils import Logging, Configuration, Utils


class Skybot(Bot):

    async def on_ready(self):
        Logging.BOT_LOG_CHANNEL = self.get_channel(Configuration.get_var("log_channel"))

        Logging.info("Loading cogs...")
        for extension in Configuration.get_var("cogs"):
            try:
                self.load_extension("cogs." + extension)
            except Exception as e:
                await Utils.handle_exception(f"Failed to load cog {extension}", self, e)
        Logging.info("Cogs loaded")

        await Logging.bot_log("Sky bot soaring through the skies!")



def before_send(event, hint):
    if event['level'] == "error" and 'logger' in event.keys() and event['logger'] == 'gearbot':
        return None  # we send errors manually, in a much cleaner way
    if 'exc_info' in hint:
        exc_type, exc_value, tb = hint['exc_info']
        for t in [ConnectionClosed, ClientOSError, ServerDisconnectedError]:
            if isinstance(exc_value, t):
                return
    return event

if __name__ == '__main__':
    Logging.init()
    Logging.info("Launching that sky bot!")

    dsn = Configuration.get_var('SENTRY_DSN', '')
    if dsn != '':
        sentry_sdk.init(dsn, before_send=before_send)

    skybot = Skybot(command_prefix="!", case_insensitive=True, guild_subscriptions=False)
    skybot.run(Configuration.get_var("token"))
    Logging.info("Shutdown complete")