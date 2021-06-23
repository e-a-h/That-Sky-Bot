from peewee import MySQLDatabase, Model, BigIntegerField, CharField, ForeignKeyField, AutoField, \
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
    id = AutoField()
    serverid = BigIntegerField()
    memberrole = BigIntegerField(default=0)
    nonmemberrole = BigIntegerField(default=0)
    mutedrole = BigIntegerField(default=0)
    betarole = BigIntegerField(default=0)
    welcomechannelid = BigIntegerField(default=0)
    ruleschannelid = BigIntegerField(default=0)
    logchannelid = BigIntegerField(default=0)
    entrychannelid = BigIntegerField(default=0)
    maintenancechannelid = BigIntegerField(default=0)
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


class BugReportingPlatform(Model):
    id = AutoField()
    platform = CharField()
    branch = CharField()

    class Meta:
        indexes = (
            # unique constraint for platform/branch
            (('platform', 'branch'), True),
        )
        database = connection


class BugReportingChannel(Model):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref='bug_channels')
    channelid = BigIntegerField(unique=True)
    platform = ForeignKeyField(BugReportingPlatform, backref="bug_channels")

    class Meta:
        indexes = (
            # unique constraint for guild/platform
            (('guild', 'platform'), True),
        )
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


class KrillConfig(Model):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref='krill_config', unique=True)
    return_home_freq = SmallIntegerField(default=0)
    shadow_roll_freq = SmallIntegerField(default=0)
    krill_rider_freq = SmallIntegerField(default=0)
    crab_freq = SmallIntegerField(default=0)
    allow_text = BooleanField(default=True)
    monster_duration = SmallIntegerField(default=21600)

    class Meta:
        database = connection


class KrillByLines(Model):
    id = AutoField()
    krill_config = ForeignKeyField(KrillConfig, backref='bylines')
    byline = CharField(max_length=100, collation="utf8mb4_general_ci")
    type = SmallIntegerField(default=0)
    channelid = BigIntegerField(default=0)
    locale = CharField(max_length=10, default='')

    class Meta:
        database = connection


class OreoMap(Model):
    id = AutoField()
    letter_o = SmallIntegerField(default=1)
    letter_r = SmallIntegerField(default=2)
    letter_e = SmallIntegerField(default=3)
    letter_oh = SmallIntegerField(default=4)
    letter_re = SmallIntegerField(default=5)
    space_char = SmallIntegerField(default=6)
    char_count = CharField(max_length=50, collation="utf8mb4_general_ci", default="{0,10}")

    class Meta:
        database = connection


class OreoLetters(Model):
    id = AutoField()
    token = CharField(max_length=50, collation="utf8mb4_general_ci", default="")
    token_class = SmallIntegerField()

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
    id = AutoField()
    serverid = BigIntegerField()
    trigger = CharField(max_length=20, collation="utf8mb4_general_ci")
    response = CharField(max_length=2000, collation="utf8mb4_general_ci")
    deletetrigger = BooleanField(default=False)
    reply = BooleanField(default=False)

    class Meta:
        database = connection


class AutoResponder(Model):
    id = AutoField()
    serverid = BigIntegerField()
    trigger = CharField(max_length=300, collation="utf8mb4_general_ci")
    response = CharField(max_length=2000, collation="utf8mb4_general_ci")
    flags = SmallIntegerField(default=0)
    chance = SmallIntegerField(default=10000)
    responsechannelid = BigIntegerField(default=0)
    listenchannelid = BigIntegerField(default=0)
    logchannelid = BigIntegerField(default=0)

    class Meta:
        database = connection


class CountWord(Model):
    id = AutoField()
    serverid = BigIntegerField()
    # guild = ForeignKeyField(Guild, backref='watchwords')
    word = CharField(max_length=300, collation="utf8mb4_general_ci")

    class Meta:
        database = connection


class ReactWatch(Model):
    id = AutoField()
    serverid = BigIntegerField()
    # guild = ForeignKeyField(Guild, backref='watchemoji')
    muteduration = SmallIntegerField(default=600)
    watchremoves = BooleanField(default=False)

    class Meta:
        database = connection


class WatchedEmoji(Model):
    id = AutoField()
    watcher = ForeignKeyField(ReactWatch, backref='emoji')
    emoji = CharField(max_length=50, collation="utf8mb4_general_ci", default="")
    log = BooleanField(default=False)
    remove = BooleanField(default=False)
    mute = BooleanField(default=False)

    class Meta:
        database = connection


class ArtChannel(Model):
    id = AutoField()
    serverid = BigIntegerField()
    # guild = ForeignKeyField(Guild, backref='artchannels')
    listenchannelid = BigIntegerField(default=0)
    collectionchannelid = BigIntegerField(default=0)
    tag = CharField(max_length=30, collation="utf8mb4_general_ci")

    class Meta:
        database = connection


class DropboxChannel(Model):
    id = AutoField()
    serverid = BigIntegerField()
    sourcechannelid = BigIntegerField()
    targetchannelid = BigIntegerField(default=0)
    deletedelayms = SmallIntegerField(default=0)

    class Meta:
        database = connection


class Localization(Model):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref='locales')
    channelid = BigIntegerField(default=0)
    locale = CharField(max_length=10, default='')

    class Meta:
        database = connection


class AdminRole(Model):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref='admin_roles')
    roleid = BigIntegerField()

    class Meta:
        database = connection


class ModRole(Model):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref='mod_roles')
    roleid = BigIntegerField()

    class Meta:
        database = connection


class BotAdmin(Model):
    id = AutoField()
    userid = BigIntegerField()

    class Meta:
        database = connection


class TrustedRole(Model):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref='trusted_roles')
    roleid = BigIntegerField()

    class Meta:
        database = connection


class UserPermission(Model):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref='command_permissions')
    userid = BigIntegerField()
    command = CharField(max_length=200, default='')
    allow = BooleanField(default=True)

    class Meta:
        database = connection


def init():
    global connection
    connection.connect()
    connection.create_tables([
        Guild,
        BotAdmin,
        AdminRole,
        ModRole,
        TrustedRole,
        UserPermission,
        ArtChannel,
        Attachments,
        AutoResponder,
        BugReport,
        ConfigChannel,
        CountWord,
        CustomCommand,
        DropboxChannel,
        KrillChannel,
        KrillConfig,
        KrillByLines,
        OreoMap,
        OreoLetters,
        Repros,
        ReactWatch,
        WatchedEmoji,
        Localization,
        BugReportingPlatform,
        BugReportingChannel
    ])
    connection.close()
