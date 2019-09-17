import yaml

LANG = dict()
loaded = False


def load():
    global LANG, loaded
    with open("lang.yaml") as file:
        LANG = yaml.safe_load(file)
    loaded = True


def get_string(key, **kwargs):
    if not loaded:
        load()
    if key not in LANG:
        raise KeyError("Unknown lang key!")
    return LANG[key].format(**kwargs)
