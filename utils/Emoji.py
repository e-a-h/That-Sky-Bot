from discord import utils

from utils import Configuration

EMOJI = dict()

BACKUPS = {
    "ANDROID": "📱",
    "BETA": "🌙",
    "BUG": "🐛",
    "IOS": "🍎",
    "NO": "🚫",
    "STABLE": "🌞",
    "WRENCH": "🔧",
    "YES": "✅"
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
