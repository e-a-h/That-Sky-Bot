import yaml

from utils import Logging, Configuration

from functools import reduce  # forward compatibility for Python 3
import operator

LANG = dict()
loaded = False
locales = ('en_US', 'ja_JP')


def get_by_path(root, items):
    """Access a nested object in root by item sequence."""
    return reduce(operator.getitem, items, root)


def load():
    global LANG, loaded
    with open("lang.yaml") as file:
        LANG = yaml.safe_load(file)
    loaded = True


def load_locales():
    global LANG, loaded
    with open("lang_keys.yaml") as file:
        LANG['keys'] = yaml.safe_load(file)
    for locale in locales:
        with open(f"langs/{locale}.yaml") as file:
            LANG[locale] = yaml.safe_load(file)
    loaded = True


def get_string(key, **kwargs):
    if not loaded:
        load()

    key_list = key.split("/")
    obj = LANG
    for i in key_list:
        if i not in obj:
            raise KeyError(f"Unknown lang key: {i}")

        if isinstance(obj[i], str):
            return obj[i].format(**kwargs)
        elif isinstance(obj[i], dict):
            obj = obj[i]


def get_locale_string(key, locale, **kwargs):
    if locale not in locales:
        Logging.bot_log(f"bad locale: {locale} for key: {key}")
    if not loaded:
        load()

    key_list = key.split("/")

    # Check that keys point to a valid path in base keys
    obj = LANG['keys']
    if get_by_path(obj, key_list) is not None:
        raise KeyError(f"lang key is not terminal: {key}")


    locale_lang = LANG[locale]
    get_by_path(locale_lang, key_list)

    for i in key_list:
        if i not in obj:
            raise KeyError(f"Unknown lang key: {i}")
        if obj[i] is None:
            continue
        elif isinstance(obj[i], dict):
            obj = obj[i]

    # keys were found. Now check locale for value:


        if isinstance(obj[i], str):
            return obj[i].format(**kwargs)
        elif isinstance(obj[i], dict):
            obj = obj[i]
