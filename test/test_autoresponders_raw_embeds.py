import asyncio
import collections
import importlib.util
import sys
import types
import unittest
from enum import IntEnum
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FakeEmbed:
    def __init__(self, *, timestamp=None, color=None, title=None):
        self.timestamp = timestamp
        self.color = color
        self.title = title
        self.fields = []

    def add_field(self, *, name, value, inline):
        self.fields.append(types.SimpleNamespace(name=name, value=value, inline=inline))


class FakeResponse:
    def __init__(self, value, active=True):
        self.value = value
        self.active = active

    def __str__(self):
        return self.value


class FakeCtx:
    def __init__(self):
        self.guild = types.SimpleNamespace(id=123)
        self.invoked = False
        self.sent_embeds = None
        self.sent_content = None

    async def invoke(self, *args, **kwargs):
        self.invoked = True
        raise AssertionError("info should build raw embeds without ctx.invoke")


class FakeRule:
    def get_info(self):
        return "rule info"


class FakeCommandFactory:
    def __call__(self, *args, **kwargs):
        def decorate(func):
            func.command = self
            func.group = self
            return func

        return decorate


def identity_decorator(*args, **kwargs):
    def decorate(func):
        return func

    return decorate


def install_import_stubs():
    discord = types.ModuleType("discord")
    discord.Embed = FakeEmbed
    discord.AllowedMentions = types.SimpleNamespace(
        none=lambda: "none",
    )
    discord.Message = type("Message", (), {})
    discord.TextChannel = type("TextChannel", (), {})
    discord.RawMessageDeleteEvent = type("RawMessageDeleteEvent", (), {})

    discord_errors = types.ModuleType("discord.errors")
    for name in ["NotFound", "HTTPException", "Forbidden"]:
        setattr(discord_errors, name, type(name, (Exception,), {}))

    commands = types.ModuleType("discord.ext.commands")
    commands.Cog = type(
        "Cog",
        (),
        {"listener": classmethod(lambda cls, *args, **kwargs: identity_decorator())},
    )
    commands.Context = type("Context", (), {})
    commands.ChannelNotFound = type("ChannelNotFound", (Exception,), {})
    commands.CommandError = type("CommandError", (Exception,), {})
    commands.BadArgument = type("BadArgument", (Exception,), {})
    commands.TextChannelConverter = type("TextChannelConverter", (), {})
    commands.group = FakeCommandFactory()
    commands.command = FakeCommandFactory()
    commands.guild_only = identity_decorator
    commands.bot_has_permissions = identity_decorator

    tasks = types.ModuleType("discord.ext.tasks")
    tasks.loop = identity_decorator

    discord_ext = types.ModuleType("discord.ext")
    discord_ext.commands = commands
    discord_ext.tasks = tasks

    discord_utils = types.ModuleType("discord.utils")
    discord_utils.utcnow = lambda: None

    tortoise_exceptions = types.ModuleType("tortoise.exceptions")
    for name in [
        "MultipleObjectsReturned",
        "DoesNotExist",
        "IntegrityError",
        "TransactionManagementError",
        "OperationalError",
        "IncompleteInstanceError",
    ]:
        setattr(tortoise_exceptions, name, type(name, (Exception,), {}))

    tortoise_query_utils = types.ModuleType("tortoise.query_utils")
    tortoise_query_utils.Prefetch = object

    base_cog = types.ModuleType("cogs.BaseCog")
    base_cog.BaseCog = type("BaseCog", (), {"__init__": lambda self, bot: setattr(self, "bot", bot)})

    utils_package = types.ModuleType("utils")
    utils_utils = types.ModuleType("utils.Utils")
    utils_utils.clean = lambda value: asyncio.sleep(0, result=value)
    for name in ["Lang", "Questions", "Emoji", "Configuration", "Logging"]:
        setattr(utils_package, name, types.ModuleType(f"utils.{name}"))
    utils_package.Utils = utils_utils

    ar_event = types.ModuleType("utils.AutoResponderEvent")
    ar_event.ArEvent = type("ArEvent", (), {})
    ar_event.ArEventFactory = type("ArEventFactory", (), {})

    ar_flags = types.ModuleType("utils.AutoResponderFlags")
    ar_flags.ArFlags = type("ArFlags", (), {})

    ar_rule = types.ModuleType("utils.AutoResponderRule")
    ar_rule.ArRule = type("ArRule", (), {})

    database = types.ModuleType("utils.Database")

    class AutoResponseType(IntEnum):
        public = 1
        mod = 2
        log = 3

    for name in ["AutoResponder", "AutoResponderChannel", "AutoResponse"]:
        setattr(database, name, type(name, (), {}))
    database.AutoResponderChannelType = type("AutoResponderChannelType", (), {})
    database.AutoResponseType = AutoResponseType

    logging_module = types.ModuleType("utils.Logging")
    logging_module.TCol = type("TCol", (), {})

    stub_modules = {
        "discord": discord,
        "discord.errors": discord_errors,
        "discord.ext": discord_ext,
        "discord.ext.commands": commands,
        "discord.ext.tasks": tasks,
        "discord.utils": discord_utils,
        "tortoise.exceptions": tortoise_exceptions,
        "tortoise.query_utils": tortoise_query_utils,
        "cogs.BaseCog": base_cog,
        "utils": utils_package,
        "utils.Utils": utils_utils,
        "utils.AutoResponderEvent": ar_event,
        "utils.AutoResponderFlags": ar_flags,
        "utils.AutoResponderRule": ar_rule,
        "utils.Database": database,
        "utils.Logging": logging_module,
    }
    originals = {name: sys.modules.get(name) for name in stub_modules}
    originals["cogs.AutoResponders"] = sys.modules.get("cogs.AutoResponders")
    sys.modules.update(stub_modules)
    return originals


def restore_import_stubs(originals):
    for name, module in originals.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def load_autoresponders_module():
    originals = install_import_stubs()
    sys.modules.pop("cogs.AutoResponders", None)
    spec = importlib.util.spec_from_file_location(
        "cogs.AutoResponders", ROOT / "cogs" / "AutoResponders.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cogs.AutoResponders"] = module
    spec.loader.exec_module(module)
    return module, originals


class RawResponseEmbedTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_responses_split_into_embeds_with_at_most_25_fields(self):
        module, originals = load_autoresponders_module()
        self.addCleanup(restore_import_stubs, originals)
        responses = collections.deque(
            FakeResponse(f"response {i}")
            for i in range(1, 27)
        )

        embeds = await module.AutoResponders.describe_raw_response_embeds(
            "created at",
            "public",
            0xc8ff00,
            responses,
        )

        self.assertEqual([len(embed.fields) for embed in embeds], [25, 1])
        self.assertEqual(embeds[0].fields[0].name, 1)
        self.assertEqual(embeds[0].fields[-1].name, 25)
        self.assertEqual(embeds[1].fields[0].name, 26)
        self.assertLessEqual(max(len(embed.fields) for embed in embeds), 25)

    async def test_info_uses_raw_embed_helper_instead_of_invoking_get_raw_command(self):
        module, originals = load_autoresponders_module()
        self.addCleanup(restore_import_stubs, originals)
        ctx = FakeCtx()
        responder = module.AutoResponders(None)
        responder.triggers = {ctx.guild.id: {"trigger": FakeRule()}}

        async def choose_trigger(_ctx, trigger):
            return trigger

        async def get_raw_embeds(_ctx, trigger):
            return [FakeEmbed(title=trigger)]

        async def send_embed_chunks(_ctx, embeds, content=""):
            _ctx.sent_embeds = embeds
            _ctx.sent_content = content

        responder.choose_trigger = choose_trigger
        responder.get_raw_embeds = get_raw_embeds
        module.AutoResponders.send_embed_chunks = send_embed_chunks

        await module.AutoResponders.info(responder, ctx, "trigger")

        self.assertFalse(ctx.invoked)
        self.assertEqual(ctx.sent_content, "rule info")
        self.assertEqual(ctx.sent_embeds[0].title, "trigger")


if __name__ == "__main__":
    unittest.main()
