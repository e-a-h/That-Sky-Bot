import re

APP_NAME = "skybot"
DISCORD_INDENT = "**\u200b \u200b **"
COLOR_LIME = 0xbefc03
THREAD_AUTO_ARCHIVE_DURATION_MAX = 10080
SIGNED_64_BIT_INTEGER_LIMIT = 9223372036854775807

# Matchers
ID_MATCHER = re.compile("<@!?([0-9]+)[\\\\]*>")
ROLE_ID_MATCHER = re.compile("<@&([0-9]+)>")
CHANNEL_ID_MATCHER = re.compile("<#([0-9]+)>")
MENTION_MATCHER = re.compile("(<@[\u200b]?[!&]?)(\\d+)[\\\\]*(>)")
NUMBER_MATCHER = re.compile(r"\d+")
EMOJI_MATCHER = re.compile('<(a?):([^: \n]+):([0-9]+)>')

URL_MATCHER = re.compile(
    r'(https?://[a-z0-9]+(?:[-._][a-z0-9]+)*\.[a-z]{2,5}(?::[0-9]{1,5})?(?:/[^ \n<>]*)?)',
    re.IGNORECASE)

INVITE_MATCHER = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord(?:\.| |\[?\(?\"?'?dot'?\"?\)?]?)?(?:gg|io|me|li)|discord(?:app)?\.com/invite)/+((?:(?!https?)[\w-])+)",
    flags=re.IGNORECASE)
