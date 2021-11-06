import tortoise.exceptions

from utils import Database
from utils.Database import *
from tortoise import Tortoise, run_async


async def run():
    # DO NOT USE THIS EXCEPT TO INIT A NEW INSTALL
    # Generate the schema
    await Database.init("test_junk")
    await Tortoise.generate_schemas()

    try:
        await Guild.create(
            serverid=123456789,
            memberrole=1,
            nonmemberrole=2,
            mutedrole=3,
            betarole=4,
            welcomechannelid=11,
            ruleschannelid=12,
            logchannelid=13,
            entrychannelid=14,
            maintenancechannelid=15,
            rulesreactmessageid=21,
            defaultlocale="en_US"
        )

        await KrillChannel.create(serverid=123456789, channelid=91)

        my_guild = await Guild.get(id=1)
        my_other_guild = await Guild.get_or_create(
            serverid=987654321,
            memberrole=7,
            nonmemberrole=8,
            mutedrole=8,
            betarole=10,
            welcomechannelid=22,
            ruleschannelid=33,
            logchannelid=44,
            entrychannelid=55,
            maintenancechannelid=66,
            rulesreactmessageid=888888,
            defaultlocale="en_US"
        )

        another_guild = await Guild.filter(serverid=987654321).first()

        await KrillConfig.create(
            guild=my_guild,
            return_home_freq=5,
            shadow_roll_freq=6,
            krill_rider_freq=7,
            crab_freq=8,
            allow_text=False,
        )
    except tortoise.exceptions.IntegrityError as e:
        print("1")
        print(type(e))
        print(e)

    try:
        await ConfigChannel.create(serverid=234567, configname="fake", channelid=9876)
    except tortoise.exceptions.IntegrityError as e:
        print("2")
        print(type(e))
        print(e)
    try:
        await CustomCommand.create(serverid=234567, trigger="ccfake", response="9876")
    except tortoise.exceptions.IntegrityError as e:
        print("3")
        print(type(e))
        print(e)
    try:
        await AutoResponder.create(serverid=234567, trigger="arfake", response="9876")
    except tortoise.exceptions.IntegrityError as e:
        print("4")
        print(type(e))
        print(e)
    try:
        await CountWord.create(serverid=234567, word="fake")
    except tortoise.exceptions.IntegrityError as e:
        print("5")
        print(type(e))
        print(e)
    try:
        await ReactWatch.create(serverid=234567)
    except tortoise.exceptions.IntegrityError as e:
        print("6")
        print(type(e))
        print(e)
    try:
        await ArtChannel.create(serverid=234567)
    except tortoise.exceptions.IntegrityError as e:
        print("7")
        print(type(e))
        print(e)
    try:
        await DropboxChannel.create(serverid=234567, sourcechannelid=98765)
    except tortoise.exceptions.IntegrityError as e:
        print("8")
        print(type(e))
        print(e)

    my_channel = await DropboxChannel.first()
    await my_channel.delete()



if __name__ == "__main__":
    print("generating schema...")
    run_async(run())
    print("Done!")
