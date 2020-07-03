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
new_field = SmallIntegerField(default=5000)
new_boolean_false = BooleanField(default=False)

# Run the migration, specifying the database table, field name and field.
migrate(
    migrator.add_column('dropboxchannel', 'deletedelayms', new_field),
    migrator.add_column('customcommand', 'delete', new_boolean_false),
)
