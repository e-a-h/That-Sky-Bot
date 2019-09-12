import json

from utils import Logging

MASTER_CONFIG = dict()
MASTER_LOADED = False

def save():
    global MASTER_CONFIG
    with open('config.json', 'w') as jsonfile:
        jsonfile.write((json.dumps(MASTER_CONFIG, indent=4, skipkeys=True, sort_keys=True)))


# Ugly but this prevents import loop errors
def load():
    global MASTER_CONFIG, MASTER_LOADED
    try:
        with open('config.json', 'r') as jsonfile:
            MASTER_CONFIG = json.load(jsonfile)
            MASTER_LOADED = True
    except FileNotFoundError:
        Logging.error("Unable to load config, running with defaults.")
    except Exception as e:
        Logging.error("Failed to parse configuration.")
        print(e)
        raise e


def get_var(key, default=None):
    global MASTER_CONFIG, MASTER_LOADED
    if not MASTER_LOADED:
        load()
    if not key in MASTER_CONFIG.keys():
        MASTER_CONFIG[key] = default
        save()
    return MASTER_CONFIG[key]