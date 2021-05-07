from playhouse.migrate import *
from utils import Configuration

connection = MySQLDatabase(Configuration.get_var("DATABASE_NAME"),
                           user=Configuration.get_var("DATABASE_USER"),
                           password=Configuration.get_var("DATABASE_PASS"),
                           host=Configuration.get_var("DATABASE_HOST"),
                           port=Configuration.get_var("DATABASE_PORT"),
                           use_unicode=True,
                           charset="utf8mb4")

migrator = MySQLMigrator(connection)

# Create your field instances. For non-null fields you must specify a
# default value.
betarole = BigIntegerField(default=0)
maintenancechannelid = BigIntegerField(default=0)

# guild = ForeignKeyField(Guild, backref='locales')

# Run the migration, specifying the database table, field name and field.
migrate(
    migrator.add_column('guild', 'betarole', betarole),
    migrator.add_column('guild', 'maintenancechannelid', maintenancechannelid)
)
