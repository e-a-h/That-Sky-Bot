from discord import utils

from utils import Configuration

EMOJI = dict()

BACKUPS = {
    "ANDROID": "🤖",
    "BETA": "🌙",
    "BUG": "<a:skyflame:624185284229201940>",
    "IOS": "🍎",
    "NO": "<:skyno:624094243371352084>",
    "STABLE": "🌞",
    "WRENCH": "<:skygear:624094243069231106>",
    "YES": "<:skyattn:624094243329146900>",
    "CANDLE": "🕯",
    "WARNING": "<:skybug:624094243308437524>",
    "WHAT": "☹",
}


def initialize(bot):
    for name, eid in Configuration.get_var("EMOJI", {}).items():
        EMOJI[name] = utils.get(bot.emojis, id=eid)


def get_chat_emoji(name):
    return str(get_emoji(name))


def get_emoji(name):
    if name in EMOJI:
        return EMOJI[name]
    else:
        return BACKUPS[name]
