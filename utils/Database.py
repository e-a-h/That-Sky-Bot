from peewee import MySQLDatabase, Model, PrimaryKeyField, BigIntegerField, CharField, ForeignKeyField, AutoField, \
    TimestampField, SmallIntegerField, BooleanField

from utils import Configuration

connection = MySQLDatabase(Configuration.get_var("DATABASE_NAME"),
                           user=Configuration.get_var("DATABASE_USER"),
                           password=Configuration.get_var("DATABASE_PASS"),
                           host=Configuration.get_var("DATABASE_HOST"),
                           port=Configuration.get_var("DATABASE_PORT"),
                           use_unicode=True,
                           charset="utf8mb4")


class Guild(Model):
    id = PrimaryKeyField()
    serverid = BigIntegerField()
    memberrole = BigIntegerField(default=0)
    nonmemberrole = BigIntegerField(default=0)
    mutedrole = BigIntegerField(default=0)
    welcomechannelid = BigIntegerField(default=0)
    ruleschannelid = BigIntegerField(default=0)
    logchannelid = BigIntegerField(default=0)
    entrychannelid = BigIntegerField(default=0)
    rulesreactmessageid = BigIntegerField(default=0)
    defaultlocale = CharField(max_length=10)

    class Meta:
        database = connection


class BugReport(Model):
    id = AutoField()
    reporter = BigIntegerField()
    message_id = BigIntegerField(unique=True, null=True)
    attachment_message_id = BigIntegerField(unique=True, null=True)
    platform = CharField(10)
    platform_version = CharField(20)
    branch = CharField(10)
    app_version = CharField(20)
    app_build = CharField(20, null=True)
    title = CharField(100, collation="utf8mb4_general_ci")
    deviceinfo = CharField(100, collation="utf8mb4_general_ci")
    steps = CharField(1024, collation="utf8mb4_general_ci")
    expected = CharField(200, collation="utf8mb4_general_ci")
    actual = CharField(400, collation="utf8mb4_general_ci")
    additional = CharField(500, collation="utf8mb4_general_ci")
    reported_at = TimestampField(utc=True)

    class Meta:
        database = connection


class Attachments(Model):
    id = AutoField()
    url = CharField(collation="utf8mb4_general_ci")
    report = ForeignKeyField(BugReport, backref="attachments")

    class Meta:
        database = connection


class Repros(Model):
    id = AutoField()
    user = BigIntegerField()
    report = ForeignKeyField(BugReport, backref="repros")

    class Meta:
        database = connection


class KrillChannel(Model):
    id = AutoField()
    channelid = BigIntegerField()
    serverid = BigIntegerField()

    class Meta:
        database = connection


class ConfigChannel(Model):
    id = AutoField()
    configname = CharField(max_length=100, collation="utf8mb4_general_ci")
    channelid = BigIntegerField(default=0)
    serverid = BigIntegerField()

    class Meta:
        database = connection


class CustomCommand(Model):
    id = PrimaryKeyField()
    serverid = BigIntegerField()
    trigger = CharField(max_length=20, collation="utf8mb4_general_ci")
    response = CharField(max_length=2000, collation="utf8mb4_general_ci")
    deletetrigger = BooleanField(default=False)

    class Meta:
        database = connection


class AutoResponder(Model):
    id = PrimaryKeyField()
    serverid = BigIntegerField()
    trigger = CharField(max_length=300, collation="utf8mb4_general_ci")
    response = CharField(max_length=2000, collation="utf8mb4_general_ci")
    flags = SmallIntegerField(default=0)
    chance = SmallIntegerField(default=10000)
    responsechannelid = BigIntegerField(default=0)
    listenchannelid = BigIntegerField(default=0)

    class Meta:
        database = connection


class CountWord(Model):
    id = PrimaryKeyField()
    serverid = BigIntegerField()
    # guild = ForeignKeyField(Guild, backref='watchwords')
    word = CharField(max_length=300, collation="utf8mb4_general_ci")

    class Meta:
        database = connection


class ReactWatch(Model):
    id = PrimaryKeyField()
    serverid = BigIntegerField()
    # guild = ForeignKeyField(Guild, backref='watchemoji')
    muteduration = SmallIntegerField(default=600)
    watchremoves = BooleanField(default=False)

    class Meta:
        database = connection


class WatchedEmoji(Model):
    id = PrimaryKeyField()
    watcher = ForeignKeyField(ReactWatch, backref='emoji')
    emoji = CharField(max_length=50, collation="utf8mb4_general_ci", default="")
    log = BooleanField(default=False)
    remove = BooleanField(default=False)
    mute = BooleanField(default=False)

    class Meta:
        database = connection


class ArtChannel(Model):
    id = PrimaryKeyField()
    serverid = BigIntegerField()
    # guild = ForeignKeyField(Guild, backref='artchannels')
    listenchannelid = BigIntegerField(default=0)
    collectionchannelid = BigIntegerField(default=0)
    tag = CharField(max_length=30, collation="utf8mb4_general_ci")

    class Meta:
        database = connection


class DropboxChannel(Model):
    id = PrimaryKeyField()
    serverid = BigIntegerField()
    sourcechannelid = BigIntegerField()
    targetchannelid = BigIntegerField(default=0)
    deletedelayms = SmallIntegerField(default=0)

    class Meta:
        database = connection


class Localization(Model):
    id = PrimaryKeyField()
    guild = ForeignKeyField(Guild, backref='locales')
    channelid = BigIntegerField(default=0)
    locale = CharField(max_length=10, default='')

    class Meta:
        database = connection


class AdminRole(Model):
    id = PrimaryKeyField()
    guild = ForeignKeyField(Guild, backref='admin_roles')
    roleid = BigIntegerField()

    class Meta:
        database = connection


class ModRole(Model):
    id = PrimaryKeyField()
    guild = ForeignKeyField(Guild, backref='mod_roles')
    roleid = BigIntegerField()

    class Meta:
        database = connection


def init():
    global connection
    connection.connect()
    connection.create_tables([
        Guild,
        ArtChannel,
        Attachments,
        AutoResponder,
        BugReport,
        ConfigChannel,
        CountWord,
        CustomCommand,
        DropboxChannel,
        KrillChannel,
        Repros,
        ReactWatch,
        WatchedEmoji,
        Localization,
        AdminRole,
        ModRole
    ])
    connection.close()
