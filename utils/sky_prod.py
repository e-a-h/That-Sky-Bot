from tortoise import Model, fields, Tortoise
from utils import tortoise_settings


async def init():
    settings = tortoise_settings.TORTOISE_ORM
    settings['connections']['default']['credentials']['database'] = 'sky_prod'
    await Tortoise.init(settings)


class Adminrole(Model):
    id = fields.IntField(pk=True, )
    guild_id = fields.IntField(index=True, )
    roleid = fields.BigIntField()


class Aerich(Model):
    id = fields.IntField(pk=True, )
    version = fields.CharField(max_length=255, )
    app = fields.CharField(max_length=100, )
    content = fields.JSONField()


class Artchannel(Model):
    id = fields.IntField(pk=True, )
    serverid = fields.BigIntField()
    listenchannelid = fields.BigIntField()
    collectionchannelid = fields.BigIntField()
    tag = fields.CharField(max_length=30, )


class Attachments(Model):
    id = fields.IntField(pk=True, )
    url = fields.CharField(max_length=255, )
    report_id = fields.IntField(index=True, )


class Autoresponder(Model):
    id = fields.IntField(pk=True, )
    serverid = fields.BigIntField()
    trigger = fields.CharField(max_length=300, )
    response = fields.CharField(max_length=2000, )
    flags = fields.BigIntField()
    chance = fields.SmallIntField()
    responsechannelid = fields.BigIntField()
    listenchannelid = fields.BigIntField()
    logchannelid = fields.BigIntField()


class Botadmin(Model):
    id = fields.IntField(pk=True, )
    userid = fields.BigIntField()


class Bugreport(Model):
    id = fields.IntField(pk=True, )
    reporter = fields.BigIntField()
    message_id = fields.BigIntField(unique=True, )
    attachment_message_id = fields.BigIntField(unique=True, )
    platform = fields.CharField(max_length=10, )
    platform_version = fields.CharField(max_length=20, )
    branch = fields.CharField(max_length=10, )
    app_version = fields.CharField(max_length=20, )
    app_build = fields.CharField(max_length=20, null=True, )
    title = fields.CharField(max_length=330, )
    steps = fields.CharField(max_length=1024, )
    expected = fields.CharField(max_length=880, )
    actual = fields.CharField(max_length=880, )
    additional = fields.CharField(max_length=500, )
    reported_at = fields.BigIntField()
    deviceinfo = fields.CharField(max_length=220, null=True, )


class Bugreportingchannel(Model):
    id = fields.IntField(pk=True, )
    channelid = fields.BigIntField(unique=True, )
    guild_id = fields.IntField(index=True, )
    platform_id = fields.IntField(index=True, )


class Bugreportingplatform(Model):
    id = fields.IntField(pk=True, )
    platform = fields.CharField(index=True, max_length=255, )
    branch = fields.CharField(index=True, max_length=255, )


class Configchannel(Model):
    id = fields.IntField(pk=True, )
    configname = fields.CharField(max_length=100, )
    channelid = fields.BigIntField()
    serverid = fields.BigIntField()


class Countword(Model):
    id = fields.IntField(pk=True, )
    serverid = fields.BigIntField()
    word = fields.CharField(max_length=300, )


class Customcommand(Model):
    id = fields.IntField(pk=True, )
    serverid = fields.BigIntField()
    trigger = fields.CharField(max_length=20, )
    response = fields.CharField(max_length=2000, )
    deletetrigger = fields.BooleanField()
    reply = fields.BooleanField()


class Dropboxchannel(Model):
    id = fields.IntField(pk=True, )
    serverid = fields.BigIntField()
    sourcechannelid = fields.BigIntField()
    targetchannelid = fields.BigIntField()
    deletedelayms = fields.SmallIntField()
    sendreceipt = fields.BooleanField()


class Guild(Model):
    id = fields.IntField(pk=True, )
    serverid = fields.BigIntField()
    memberrole = fields.BigIntField()
    nonmemberrole = fields.BigIntField()
    mutedrole = fields.BigIntField()
    welcomechannelid = fields.BigIntField()
    ruleschannelid = fields.BigIntField()
    logchannelid = fields.BigIntField()
    entrychannelid = fields.BigIntField()
    rulesreactmessageid = fields.BigIntField()
    defaultlocale = fields.CharField(max_length=10, )
    betarole = fields.BigIntField()
    maintenancechannelid = fields.BigIntField()


class Krillbylines(Model):
    id = fields.IntField(pk=True, )
    krill_config_id = fields.IntField(index=True, )
    byline = fields.CharField(max_length=100, )
    type = fields.SmallIntField()
    channelid = fields.BigIntField()
    locale = fields.CharField(max_length=10, )


class Krillchannel(Model):
    id = fields.IntField(pk=True, )
    channelid = fields.BigIntField()
    serverid = fields.BigIntField()


class Krillconfig(Model):
    id = fields.IntField(pk=True, )
    guild_id = fields.IntField(unique=True, )
    return_home_freq = fields.SmallIntField()
    shadow_roll_freq = fields.SmallIntField()
    krill_rider_freq = fields.SmallIntField()
    crab_freq = fields.SmallIntField()
    allow_text = fields.BooleanField()
    monster_duration = fields.SmallIntField()


class Localization(Model):
    id = fields.IntField(pk=True, )
    guild_id = fields.IntField(index=True, )
    channelid = fields.BigIntField()
    locale = fields.CharField(max_length=10, )


class Modrole(Model):
    id = fields.IntField(pk=True, )
    guild_id = fields.IntField(index=True, )
    roleid = fields.BigIntField()


class Oreoletters(Model):
    id = fields.IntField(pk=True, )
    token = fields.CharField(max_length=50, )
    token_class = fields.SmallIntField()


class Oreomap(Model):
    id = fields.IntField(pk=True, )
    letter_o = fields.SmallIntField()
    letter_r = fields.SmallIntField()
    letter_e = fields.SmallIntField()
    letter_oh = fields.SmallIntField()
    letter_re = fields.SmallIntField()
    space_char = fields.SmallIntField()
    char_count = fields.CharField(max_length=50, )


class Reactwatch(Model):
    id = fields.IntField(pk=True, )
    serverid = fields.BigIntField()
    watchremoves = fields.BooleanField()
    muteduration = fields.SmallIntField()


class Repros(Model):
    id = fields.IntField(pk=True, )
    user = fields.BigIntField()
    report_id = fields.IntField(index=True, )


class Trustedrole(Model):
    id = fields.IntField(pk=True, )
    guild_id = fields.IntField(index=True, )
    roleid = fields.BigIntField()


class Userpermission(Model):
    id = fields.IntField(pk=True, )
    guild_id = fields.IntField(index=True, )
    userid = fields.BigIntField()
    command = fields.CharField(max_length=200, )
    allow = fields.BooleanField()


class Watchedemoji(Model):
    id = fields.IntField(pk=True, )
    watcher_id = fields.IntField(index=True, )
    emoji = fields.CharField(max_length=50, null=True, )
    log = fields.BooleanField()
    remove = fields.BooleanField()
    mute = fields.BooleanField()
