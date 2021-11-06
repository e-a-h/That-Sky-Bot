from tortoise import Tortoise
from tortoise.models import Model
from tortoise.fields import \
    BooleanField, BigIntField, IntField, SmallIntField, CharField, ForeignKeyField, DatetimeField, ManyToManyField
from utils import Configuration


async def init(db_name=''):
    # TODO: migrations
    #  get_or_none
    #  get_or_create
    #  **** create
    #  select where
    #  get
    #  delete_instance
    #  **** save
    #

    #  specify the app name of "models"
    #  which contain models from "app.models"

    db_name = Configuration.get_var("DATABASE_NAME") if db_name == '' else db_name
    db_user = Configuration.get_var("DATABASE_USER")
    db_pass = Configuration.get_var("DATABASE_PASS")
    db_host = Configuration.get_var("DATABASE_HOST")
    db_port = Configuration.get_var("DATABASE_PORT")

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
                'skybot': {'models': ['utils.Database']}
            },
            'use_tz': False,
            'timezone': 'UTC'
        }
    )


class AbstractBaseModel(Model):
    id = IntField(pk=True)

    class Meta:
        abstract = True


class DeprecatedServerIdMixIn:
    serverid = BigIntField(unique=True)


class GuildMixin:
    guild = ForeignKeyField('skybot.Guild', related_name='krill_config', unique=True)


class Guild(AbstractBaseModel):
    serverid = BigIntField(unique=True)
    memberrole = BigIntField(default=0)
    nonmemberrole = BigIntField(default=0)
    mutedrole = BigIntField(default=0)
    betarole = BigIntField(default=0)
    welcomechannelid = BigIntField(default=0)
    ruleschannelid = BigIntField(default=0)
    logchannelid = BigIntField(default=0)
    entrychannelid = BigIntField(default=0)
    maintenancechannelid = BigIntField(default=0)
    rulesreactmessageid = BigIntField(default=0)
    defaultlocale = CharField(max_length=10)

    def __str__(self):
        return self.serverid

    class Meta:
        table = "guild"


class BugReport(AbstractBaseModel):
    reporter = BigIntField()
    message_id = BigIntField(unique=True, null=True)
    attachment_message_id = BigIntField(unique=True, null=True)
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
    reported_at = DatetimeField(utc=True)

    def __str__(self):
        return f"{self.reporter}: {self.title}"

    class Meta:
        table = "bugreport"


class BugReportingPlatform(AbstractBaseModel):
    platform = CharField(100)
    branch = CharField(20)

    def __str__(self):
        return f"{self.platform}_{self.branch}"

    class Meta:
        # unique constraint for platform/branch
        unique_together = ('platform', 'branch')
        indexes = ('platform', 'branch')
        table = "bugreportingplatform"


class BugReportingChannel(AbstractBaseModel):
    guild = ForeignKeyField('skybot.Guild', related_name='bug_channels')
    channelid = BigIntField(unique=True)
    platform = ForeignKeyField('skybot.BugReportingPlatform', related_name="bug_channels")

    def __str__(self):
        return str(self.channelid)

    class Meta:
        # unique constraint for guild/platform
        unique_together = ('guild', 'platform')
        indexes = ('guild', 'platform')
        table = "bugreportingchannel"


class Attachments(AbstractBaseModel):
    url = CharField(max_length=255, collation="utf8mb4_general_ci")
    report = ForeignKeyField('skybot.BugReport', related_name="attachments")

    def __str__(self):
        return self.url

    class Meta:
        table = "attachments"


class Repros(AbstractBaseModel):
    user = BigIntField()
    report = ForeignKeyField('skybot.BugReport', related_name="repros")

    def __str__(self):
        return f"repro #{self.id} (unused)"

    class Meta:
        table = "repros"


class KrillChannel(AbstractBaseModel, DeprecatedServerIdMixIn):
    channelid = BigIntField()

    def __str__(self):
        return str(self.channelid)

    class Meta:
        table = "krillchannel"


class KrillConfig(AbstractBaseModel):
    guild = ForeignKeyField('skybot.Guild', related_name='krill_config', unique=True)
    return_home_freq = SmallIntField(default=0)
    shadow_roll_freq = SmallIntField(default=0)
    krill_rider_freq = SmallIntField(default=0)
    crab_freq = SmallIntField(default=0)
    allow_text = BooleanField(default=True)
    monster_duration = SmallIntField(default=21600)

    def __str__(self):
        return self.guild.id

    class Meta:
        table = "krillconfig"


class KrillByLines(AbstractBaseModel):
    krill_config = ForeignKeyField('skybot.KrillConfig', related_name='bylines')
    byline = CharField(max_length=100, collation="utf8mb4_general_ci")
    type = SmallIntField(default=0)
    channelid = BigIntField(default=0)
    locale = CharField(max_length=10, default='')

    def __str__(self):
        return self.byline

    class Meta:
        table = "krillbylines"


class OreoMap(AbstractBaseModel):
    letter_o = SmallIntField(default=1)
    letter_r = SmallIntField(default=2)
    letter_e = SmallIntField(default=3)
    letter_oh = SmallIntField(default=4)
    letter_re = SmallIntField(default=5)
    space_char = SmallIntField(default=6)
    char_count = CharField(max_length=50, collation="utf8mb4_general_ci", default="{0,10}")

    def __str__(self):
        return "enum mapping"

    class Meta:
        table = "oreomap"


class OreoLetters(AbstractBaseModel):
    token = CharField(max_length=50, collation="utf8mb4_general_ci", default="")
    token_class = SmallIntField()

    def __str__(self):
        return self.token

    class Meta:
        table = "oreoletters"


class ConfigChannel(AbstractBaseModel, DeprecatedServerIdMixIn):
    configname = CharField(max_length=100, collation="utf8mb4_general_ci")
    channelid = BigIntField(default=0)

    def __str__(self):
        return str(self.channelid)

    class Meta:
        table = "configchannel"


class CustomCommand(AbstractBaseModel, DeprecatedServerIdMixIn):
    trigger = CharField(max_length=20, collation="utf8mb4_general_ci")
    response = CharField(max_length=2000, collation="utf8mb4_general_ci")
    deletetrigger = BooleanField(default=False)
    reply = BooleanField(default=False)

    def __str__(self):
        return self.trigger

    class Meta:
        table = "customcommand"


class AutoResponder(AbstractBaseModel, DeprecatedServerIdMixIn):
    trigger = CharField(max_length=300, collation="utf8mb4_general_ci")
    response = CharField(max_length=2000, collation="utf8mb4_general_ci")
    flags = SmallIntField(default=0)
    chance = SmallIntField(default=10000)
    responsechannelid = BigIntField(default=0)
    listenchannelid = BigIntField(default=0)
    logchannelid = BigIntField(default=0)

    def __str__(self):
        return self.trigger

    class Meta:
        table = "autoresponder"


class CountWord(AbstractBaseModel, DeprecatedServerIdMixIn):
    # guild = ForeignKeyField('skybot.Guild', related_name='watchwords')
    word = CharField(max_length=300, collation="utf8mb4_general_ci")

    def __str__(self):
        return self.word

    class Meta:
        table = "countword"


class ReactWatch(AbstractBaseModel, DeprecatedServerIdMixIn):
    # guild = ForeignKeyField('skybot.Guild', related_name='watchemoji')
    muteduration = SmallIntField(default=600)
    watchremoves = BooleanField(default=False)

    def __str__(self):
        return f"Server: {self.serverid} - Mute Time: {self.muteduration}s - " \
               f"Watching for react removal: {'YES' if self.watchremoves else 'NO'}"

    class Meta:
        table = "reactwatch"


class WatchedEmoji(AbstractBaseModel):
    watcher = ForeignKeyField('skybot.ReactWatch', related_name='emoji')
    emoji = CharField(max_length=50, collation="utf8mb4_general_ci", default="")
    log = BooleanField(default=False)
    remove = BooleanField(default=False)
    mute = BooleanField(default=False)

    def __str__(self):
        return self.emoji

    class Meta:
        table = "watchedemoji"


class ArtChannel(AbstractBaseModel, DeprecatedServerIdMixIn):
    # guild = ForeignKeyField('skybot.Guild', related_name='artchannels')
    listenchannelid = BigIntField(default=0)
    collectionchannelid = BigIntField(default=0)
    tag = CharField(max_length=30, collation="utf8mb4_general_ci", default="")

    def __str__(self):
        return str(self.listenchannelid)

    class Meta:
        table = "artchannel"


class DropboxChannel(AbstractBaseModel, DeprecatedServerIdMixIn):
    sourcechannelid = BigIntField()
    targetchannelid = BigIntField(default=0)
    deletedelayms = SmallIntField(default=0)

    def __str__(self):
        return str(self.sourcechannelid)

    class Meta:
        table = "dropboxchannel"


class Localization(AbstractBaseModel):
    guild = ForeignKeyField('skybot.Guild', related_name='locales')
    channelid = BigIntField(default=0)
    locale = CharField(max_length=10, default='')

    def __str__(self):
        return f"{self.channelid}: {self.locale}"

    class Meta:
        table = "localization"


class AdminRole(AbstractBaseModel):
    guild = ForeignKeyField('skybot.Guild', related_name='admin_roles')
    roleid = BigIntField()

    def __str__(self):
        return str(self.roleid)

    class Meta:
        table = "adminrole"


class ModRole(AbstractBaseModel):
    guild = ForeignKeyField('skybot.Guild', related_name='mod_roles')
    roleid = BigIntField()

    def __str__(self):
        return str(self.roleid)

    class Meta:
        table = "modrole"


class BotAdmin(AbstractBaseModel):
    userid = BigIntField()

    def __str__(self):
        return str(self.userid)

    class Meta:
        table = "botadmin"


class TrustedRole(AbstractBaseModel):
    roleid = BigIntField()
    guild = ForeignKeyField('skybot.Guild', related_name='trusted_roles', index=True)

    def __str__(self):
        return str(self.roleid)

    class Meta:
        table = "trustedrole"


class UserPermission(AbstractBaseModel):
    guild = ForeignKeyField('skybot.Guild', related_name='command_permissions')
    userid = BigIntField()
    command = CharField(max_length=200, default='')
    allow = BooleanField(default=True)

    def __str__(self):
        return str(self.userid)

    class Meta:
        table = "userpermission"
