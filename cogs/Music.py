import os
import re
import sys

from discord.ext import commands

from cogs.BaseCog import BaseCog

from modes import InputMode, RenderMode, CSSMode
from parsers import SongParser
from songs import Song

from utils import Lang, Emoji


class Music(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        # Parameters that can be changed by advanced users
        self.QUAVER_DELIMITER = '-'  # Dash-separated list of chords
        self.ICON_DELIMITER = ' '  # Chords separation
        self.NOTE_WIDTH = "1em"  # Any CSS-compatible unit can be used
        self.PAUSE = '.'
        self.COMMENT_DELIMITER = '#'  # Lyrics delimiter, can be used for comments
        self.REPEAT_INDICATOR = '*'
        self.SONG_DIR_IN = 'songs'
        self.SONG_DIR_OUT = 'songs'
        self.CSS_PATH = 'css/main.css'
        self.CSS_MODE = CSSMode.EMBED
        self.ENABLED_MODES = [RenderMode.HTML, RenderMode.SVG, RenderMode.PNG, RenderMode.SKYASCII,
                              RenderMode.JIANPUASCII, RenderMode.WESTERNASCII]
        self.my_parser = SongParser()  # Create a parser object

    ### Define Errors
    # class Error(Exception):
    #    """Base class for exceptions in this module."""
    #    pass
    def ask_for_mode(self, modes):

        mydict = {}
        i = 0
        print('Please choose your note format:\n')
        if InputMode.SKYKEYBOARD in modes:
            i += 1
            print(
                str(i) + ') ' + InputMode.SKYKEYBOARD.value[2] +
                '\n   ' +
                self.my_parser.keyboard_layout.replace(' ', '\n   ') +
                ':')
            mydict[i] = InputMode.SKYKEYBOARD
        if InputMode.SKY in modes:
            i += 1
            print(str(i) + ') ' + InputMode.SKY.value[2])
            mydict[i] = InputMode.SKY
        if InputMode.WESTERN in modes:
            i += 1
            print(str(i) + ') ' + InputMode.WESTERN.value[2])
            mydict[i] = InputMode.WESTERN
        if InputMode.JIANPU in modes:
            i += 1
            print(str(i) + ') ' + InputMode.JIANPU.value[2])
            mydict[i] = InputMode.JIANPU
        if InputMode.WESTERNCHORDS in modes:
            i += 1
            print(str(i) + ') ' + InputMode.WESTERNCHORDS.value[2])
            mydict[i] = InputMode.WESTERNCHORDS
        try:
            song_notation = int(input("Mode (1-" + str(i) + "): ").strip())
            mode = mydict[song_notation]
        except (ValueError, KeyError):
            mode = InputMode.SKY
        return mode

    def is_file(self, string):
        isfile = False
        fp = os.path.join(self.SONG_DIR_IN, os.path.normpath(string))
        isfile = os.path.isfile(fp)

        if not (isfile):
            fp = os.path.join(self.SONG_DIR_IN, os.path.normpath(string + '.txt'))
            isfile = os.path.isfile(fp)

        if not (isfile):
            fp = os.path.join(os.path.normpath(string))
            isfile = os.path.isfile(fp)

        if not (isfile):
            splitted = os.path.splitext(string)
            if len(splitted[0]) > 0 and len(splitted[1]) > 2 and len(splitted[1]) <= 5:  # then probably a file name
                while not (isfile) and len(fp) > 2:
                    print('\nFile not found.')
                    isfile, fp = self.is_file(input(
                        'File name (in ' + os.path.normpath(self.SONG_DIR_IN) + '/): ').strip())

        return isfile, fp

    @commands.command(aliases=['ts', 'song'])
    async def transcribe_song(self, ctx):
        ### Change directory
        # mycwd = os.getcwd()
        # os.chdir("..")
        # if not os.path.isdir(self.SONG_DIR_OUT):
        #     os.mkdir(self.SONG_DIR_OUT)

        ### MAIN SCRIPT

        start_prompt = Lang.get_string('music/start_prompt_01')

        qwer = self.my_parser.keyboard_layout.replace(' ', '\n   ')
        qwer = re.sub(r'(\w)', r'\1 ', qwer)
        mode2 = str(InputMode.SKY.value[2]).split('\n')
        abc123 = mode2.pop(0)
        abc123 += "```"+'\n'.join(mode2)+"```"

        start_prompt += f"""
{Emoji.get_chat_emoji("YES")} {InputMode.SKYKEYBOARD.value[2]}```
   {qwer}```

{Emoji.get_chat_emoji("YES")} {abc123}

{Emoji.get_chat_emoji("YES")} {InputMode.WESTERN.value[2]}

{Emoji.get_chat_emoji("YES")} {InputMode.JIANPU.value[2]}

{Emoji.get_chat_emoji("YES")} {InputMode.WESTERNCHORDS.value[2]}
"""
        start_prompt += '\n'
        start_prompt += Lang.get_string('music/start_prompt_02',
                                        ICON_DELIMITER=self.ICON_DELIMITER,
                                        PAUSE=self.PAUSE,
                                        QUAVER_DELIMITER=self.QUAVER_DELIMITER,
                                        REPEAT_INDICATOR=self.REPEAT_INDICATOR)

        await ctx.send(start_prompt)
        return

def setup(bot):
    bot.add_cog(Music(bot))
