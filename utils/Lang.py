from utils import Utils

LANG = dict()
loaded = False


def load():
    global LANG, loaded
    LANG = Utils.fetch_from_disk("lang")
    loaded = True


def get_string(key, **kwargs):
    if not loaded:
        load()
    if key not in LANG:
        raise KeyError("Unknown lang key!")
    return LANG[key].format(**kwargs)
