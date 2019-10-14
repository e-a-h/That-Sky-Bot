import inspect

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

    key_list = key.split("/")
    obj = LANG
    for i in key_list:
        if i not in obj:
            raise KeyError("Unknown lang key!")

        if isinstance(obj[i], str):
            return obj[i].format(**kwargs)
        elif isinstance(obj[i], dict):
            obj = obj[i]


def get_cog_string(key, **kwargs):
    """Get string from group named for calling class"""
    stack = inspect.stack()
    calling_class = ""
    # get the name of the calling class
    for i, frame in enumerate(stack):
        if frame.function is "get_cog_string":
            calling_class = str(stack[i+1][0].f_locals["self"].__class__.__name__).lower()
            break
    return get_string(f'{calling_class}/{key}', **kwargs)
