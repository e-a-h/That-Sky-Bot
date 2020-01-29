import os
import re
import sys

from discord.ext import commands

from cogs.BaseCog import BaseCog

from modes import InputMode, RenderMode, CSSMode, ResponseMode
from parsers import SongParser
from responder import Responder
from songs import Song

from utils import Lang, Emoji


class BotResponder(Responder):

    def init_working_directory(self):

        pass

    def ask(self, question):
        user_response = None

        if self.get_response_mode() == ResponseMode.BOT:
            # TODO: rewrite these methods
            pass

        return user_response

    def output(self, output):

        if self.get_response_mode() == ResponseMode.BOT:
            print(output)

    def create_song(self):

        self.set_parser(SongParser(self))

        os.chdir(self.get_directory_base())

        self.output_instructions()

        first_line = self.ask_first_line()
        fp = self.load_file(self.get_song_dir_in(), first_line)  # loads file or asks for next line
        song_lines = self.read_lines(first_line, fp)

        # Parse song
        self.ask_input_mode(song_lines)
        song_key = self.ask_song_key(self.get_parser().get_input_mode(), song_lines)
        note_shift = self.ask_note_shift()
        self.set_song(self.parse_song(song_lines, song_key, note_shift))

        self.calculate_error_ratio()

        # Song information
        self.ask_song_title()
        self.ask_song_headers(song_key)

        # Output
        if self.get_response_mode() == ResponseMode.COMMAND_LINE:
            self.write_song_to_files()
        elif ResponseMode.BOT:
            # TODO: choose RenderMode according to player request
            self.send_song_to_channel(RenderMode.PNG)
        else:
            return


class Music(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.responder = BotResponder()
        self.responder.set_response_mode(ResponseMode.BOT)
        print(os.getcwd())
        # self.responder.create_song_bot()  # Create a parser object
        # new commands from the program can be put under here

    @commands.command(aliases=['ts', 'song'])
    async def transcribe_song(self, ctx):
        # ## MAIN SCRIPT

        start_prompt = Lang.get_string('music/start_prompt_01')

        #start_prompt += f"""
        # """
        # start_prompt += '\n'
        # start_prompt += Lang.get_string('music/start_prompt_02',
        #                                 ICON_DELIMITER=' ',
        #                                 PAUSE='.',
        #                                 QUAVER_DELIMITER='-',
        #                                 REPEAT_INDICATOR='*')

        await ctx.send(start_prompt)
        return


def setup(bot):
    bot.add_cog(Music(bot))
