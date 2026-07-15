from enum import IntFlag

from utils import Utils
from utils.Constants import DISCORD_INDENT


class ArFlags(IntFlag):
    ACTIVE = 1 << 0
    FULL_MATCH = 1 << 1
    DELETE = 1 << 2
    MATCH_CASE = 1 << 3
    IGNORE_MOD = 1 << 4
    MOD_ACTION = 1 << 5
    LOG_ONLY = 1 << 6
    DM_RESPONSE = 1 << 7
    DELETE_WHEN_TRIGGER_DELETED = 1 << 8
    DELETE_ON_MOD_RESPOND = 1 << 9
    USE_REPLY = 1 << 10

    def __str__(self):
        flags = []
        for i in ArFlags:
            # if the flag is set and has a name, add it to the display list
            if (self & i) and i.name:
                flags.append(i.name.lower())
        return ", ".join(flags)

    @staticmethod
    def init_by_bitshift(value: int):
        if not ArFlags.bitshift_is_valid_flag(value):
            raise ValueError
        return ArFlags(1 << value)

    @staticmethod
    def get_name_by_bitshift(value: int):
        flag = ArFlags.init_by_bitshift(value)
        return flag.name.lower() if flag.name else "unknown"

    @staticmethod
    def get_all_names():
        return [i.name.lower() for i in ArFlags if i.name]

    @staticmethod
    def bitshift_is_valid_flag(value: int) -> bool:
        return value >= 0 and Utils.is_power_of_two(1 << value) and 1 << value in [int(i) for i in ArFlags]

    def get_flags_description(self, pre=None) -> str:
        """Get a Markdown-formatted description of the flags set in this instance

        Parameters
        ----------
        pre: str
            An optional prefix to add to the beginning of the description.
            When omitted, the default is DISCORD_INDENT (renders in discord as blank spaces).

        Returns
        -------
        str
            A Description of which flags are set, or "DISABLED" if not active, formatted as Markdown
        """
        #
        pre = pre or DISCORD_INDENT
        if self & ArFlags.ACTIVE:
            return f'{pre} Flags: **{self}**'
        return f"{pre} ***DISABLED***"
