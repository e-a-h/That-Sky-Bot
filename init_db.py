from tortoise import Tortoise,  connections, run_async
import sys
from utils import Database
from utils.Database import *
import re


async def run(schema_name):
    if not schema_name:
        print("schema name > ", end="")
        schema_name = input()

    schema_name = re.sub(r'[^a-zA-Z0-9_]+', '_', schema_name.strip())
    if not schema_name:
        print("Can't operate without a valid schema name. Exiting.")
        exit()
    print(f"Generating schema in database `{schema_name}`")

    # Generate the schema
    # DO NOT USE THIS EXCEPT TO INIT A NEW INSTALL
    await Database.init(schema_name)
    conn = connections.get("default")
    await Tortoise.generate_schemas(safe=True)


if __name__ == "__main__":
    schema = None
    try:
        if len(sys.argv[1:]) == 1:
            schema = sys.argv[1]
        if len(sys.argv[1:]) > 1:
            print("Provide a schema name")
            raise Exception
        run_async(run(schema))
    except Exception:
        print(">> failed. make sure the database exists and matches the name you gave <<")
        exit()

    print("Done!")
