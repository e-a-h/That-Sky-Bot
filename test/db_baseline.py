from tortoise import Tortoise, run_async

from utils import sky_prod


async def run():
    await sky_prod.init()

    # Need to get a connection. Unless explicitly specified, the name should be 'default'
    conn = Tortoise.get_connection("default")

    # Now we can execute queries in the normal autocommit mode
    drops = [
        "drop table adminrole;",
        "drop table aerich;",
        "drop table artchannel;",
        "drop table attachments;",
        "drop table autoresponder;",
        "drop table botadmin;",
        "drop table bugreportingchannel;",
        "drop table bugreportingplatform;",
        "drop table configchannel;",
        "drop table countword;",
        "drop table customcommand;",
        "drop table dropboxchannel;",
        "drop table krillbylines;",
        "drop table krillchannel;",
        "drop table krillconfig;",
        "drop table localization;",
        "drop table modrole;",
        "drop table oreoletters;",
        "drop table oreomap;",
        "drop table repros;",
        "drop table bugreport;",
        "drop table trustedrole;",
        "drop table userpermission;",
        "drop table guild;",
        "drop table watchedemoji;",
        "drop table reactwatch;"
    ]
    for query in drops:
        try:
            await conn.execute_query(query)
        except Exception as e:
            pass

    print("generating schema...")
    await Tortoise.generate_schemas()


if __name__ == "__main__":
    run_async(run())
    print("Done!")
