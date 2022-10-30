"""
This example demonstrates SQL Schema generation for each DB type supported.
"""
import tortoise
from tortoise import Tortoise, fields, run_async
from tortoise.models import Model
from tortoise.utils import get_schema_sql


class Tournament(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, description="Tournament name", index=True)
    created = fields.DatetimeField(auto_now_add=True, description="Created datetime")

    events: fields.ReverseRelation["Event"]

    class Meta:
        table_description = "What Tournaments we have"


class Event(Model):
    id = fields.IntField(pk=True, description="Event ID")
    name = fields.CharField(max_length=255, unique=True)
    tournament: fields.ForeignKeyRelation[Tournament] = fields.ForeignKeyField(
        "my_app.Tournament", related_name="events", description="FK to tournament"
    )
    participants: fields.ManyToManyRelation["Team"] = fields.ManyToManyField(
        "my_app.Team",
        related_name="events",
        through="event_team",
        description="How participants relate",
    )
    modified = fields.DatetimeField(auto_now=True)
    prize = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    token = fields.CharField(max_length=100, description="Unique token", unique=True)

    class Meta:
        table_description = "This table contains a list of all the events"


class Team(Model):
    name = fields.CharField(max_length=50, pk=True, description="The TEAM name (and PK)")

    events: fields.ManyToManyRelation[Event]

    class Meta:
        table_description = "The TEAMS!"


async def run():
    print("\n\nMySQL:\n")
    db_name = "test_junk"
    db_user = "root"
    db_pass = "Do11ies1"
    db_host = "localhost"
    db_port = 3306

    await Tortoise.init(
        config={
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
                'my_app': {
                    'models': ['__main__']
                }
            },
            'use_tz': False,
            'timezone': 'UTC'
        }
    )

    sql = get_schema_sql(Tortoise.get_connection("default"), safe=False)
    print(sql)
    # await Tortoise.generate_schemas()


if __name__ == "__main__":
    print("starting...")
    run_async(run())
    print("ending...")
