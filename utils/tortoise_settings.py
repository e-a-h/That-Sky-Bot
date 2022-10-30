import os

from utils import Configuration

db_model = 'utils.Database'
db_name = Configuration.get_var("DATABASE_NAME")
db_user = Configuration.get_var("DATABASE_USER")
db_pass = Configuration.get_var("DATABASE_PASS")
db_host = Configuration.get_var("DATABASE_HOST")
db_port = Configuration.get_var("DATABASE_PORT")

# env var SKYBOT_DB will override db name from both init call AND config.json
override_db_name = os.getenv('SKYBOT_DB')
if override_db_name:
    db_name = override_db_name

override_model_name = os.getenv('SKYBOT_MODEL')
if override_model_name:
    db_model = override_model_name

TORTOISE_ORM = {
    'connections': {
        'default': {
            'engine': 'tortoise.backends.mysql',
            'credentials': {
                'host': db_host,
                'port': db_port,
                'user': db_user,
                'password': db_pass,
                'database': db_name,
            }
        }
    },
    'apps': {
        'skybot': {'models': [db_model, 'aerich.models']}
    },
    'use_tz': False,
    'timezone': 'UTC'
}
