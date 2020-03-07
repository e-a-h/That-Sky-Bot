import asyncio
import os
import re
from concurrent.futures import CancelledError

from discord import Forbidden, File
from discord.ext import commands

from cogs.BaseCog import BaseCog

try:
    from modes import InputModes, RenderModes, CSSModes
    from parsers import SongParser
    from songs import Song
except ImportError as e:
    print(e)

from utils import Lang, Emoji, Questions, Utils, Configuration


class Music(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.music_messages = set()
        self.in_progress = dict()
        self.sweeps = dict()
        m = self.bot.metrics
        m.reports_in_progress.set_function(lambda: len(self.in_progress))

    async def delete_progress(self, uid):
        if uid in self.in_progress:
            self.in_progress[uid].cancel()
            del self.in_progress[uid]
        if uid in self.sweeps:
            self.sweeps[uid].cancel()

    async def sweep_trash(self, user):
        await asyncio.sleep(Configuration.get_var("bug_trash_sweep_minutes") * 60)
        if user.id in self.in_progress:
            if not self.in_progress[user.id].done() or not self.in_progress[user.id].cancelled():
                await user.send(Lang.get_string("bugs/sweep_trash"))

            await self.delete_progress(user.id)

    @commands.command(aliases=['ts', 'song'])
    async def transcribe_song(self, ctx):

        m = self.bot.metrics
        active_question = None
        restarting = False

        # Parameters that can be changed by advanced users
        QUAVER_DELIMITER = '-'  # Dash-separated list of chords
        ICON_DELIMITER = ' '  # Chords separation
        PAUSE = '.'
        COMMENT_DELIMITER = '#'  # Lyrics delimiter, can be used for comments
        REPEAT_INDICATOR = '*'
        SONG_DIR_IN = 'test_songs'
        MUSIC_SUBMODULE_PATH = 'sky-python-music-sheet-maker'
        SONG_DIR_OUT = 'songs_out'
        CSS_PATH = 'css/main.css'
        CSS_MODE = CSSModes.EMBED
        ENABLED_MODES = [RenderModes.SKYASCII, RenderModes.PNG]

        mycwd = os.getcwd()

        if not os.path.isdir(os.path.join(MUSIC_SUBMODULE_PATH, SONG_DIR_OUT)):
            os.mkdir(os.path.join(MUSIC_SUBMODULE_PATH, SONG_DIR_OUT))

        SONG_DIR_OUT = os.path.join(MUSIC_SUBMODULE_PATH, SONG_DIR_OUT)

        # delete the author's message

        # start a dm
        try:
            channel = await ctx.author.create_dm()
            asking = True

            async def abort():
                nonlocal asking
                await ctx.author.send(Lang.get_string("bugs/abort_report"))
                asking = False
                m.reports_abort_count.inc()
                m.reports_exit_question.observe(active_question)
                await self.delete_progress(ctx.author.id)

            def max_length(length):
                def real_check(text):
                    if len(text) > length:
                        return Lang.get_string("music/text_too_long", max=length)
                    return True

                return real_check

            #
            song = await Questions.ask_text(self.bot, channel, ctx.author,
                                            Lang.get_string("music/start_prompt_01",
                                                            PAUSE=PAUSE,
                                                            QUAVER_DELIMITER=QUAVER_DELIMITER,
                                                            REPEAT_INDICATOR=REPEAT_INDICATOR,
                                                            COMMENT_DELIMITER=COMMENT_DELIMITER,
                                                            max=100),
                                            validator=max_length(2000))
            myparser = SongParser()

            song_lines = song.split('\n')
            print(song_lines)

            possible_modes = myparser.get_possible_modes(song_lines)

            if len(possible_modes) > 1:
                await channel.send('\nSeveral possible notations detected.\n Please choose your note format:\n')

                mydict = {}
                i = 0
                for mode in possible_modes:
                    i += 1
                    await channel.send(str(i) + ') ' + mode.value[2])
                    if mode == InputModes.SKYKEYBOARD:
                        await channel.send('   ' + myparser.get_keyboard_layout().replace(' ', '\n   ') + ':')
                    mydict[i] = mode
                try:
                    notation = await Questions.ask_text(self.bot, channel, ctx.author,
                                                        "Mode (1-" + str(i) + "): ",
                                                        validator=max_length(50))
                    song_notation = mydict[int(notation.strip())]
                except (ValueError, KeyError):
                    song_notation = InputModes.SKY

            elif len(possible_modes) == 0:
                await channel.send('\nCould not detect your note format. Maybe your song contains typo errors?\nPlease choose your note format:\n')
                mydict = {}
                i = 0
                for mode in possible_modes:
                    i += 1
                    await channel.send(str(i) + ') ' + mode.value[2])
                    if mode == InputModes.SKYKEYBOARD:
                        await channel.send('   ' + myparser.get_keyboard_layout().replace(' ', '\n   ') + ':')
                    mydict[i] = mode
                try:
                    notation = await Questions.ask_text(self.bot, channel, ctx.author,
                                                        "Mode (1-" + str(i) + "): ",
                                                        validator=max_length(50))
                    song_notation = mydict[int(notation.strip())]
                except (ValueError, KeyError):
                    song_notation = InputModes.SKY
            else:
                await channel.send(
                    '\nWe detected that you use the following notation: ' + possible_modes[0].value[1] + '.')
                song_notation = possible_modes[0]

            myparser.set_input_mode(song_notation)

            if song_notation == InputModes.JIANPU and PAUSE != '0':
                await channel.send('\nWarning: pause in Jianpu has been reset to ''0''.')
                PAUSE = '0'

            myparser.set_delimiters(ICON_DELIMITER, PAUSE, QUAVER_DELIMITER, COMMENT_DELIMITER, REPEAT_INDICATOR)

            possible_keys = []
            song_key = None
            if song_notation in [InputModes.ENGLISH, InputModes.DOREMI, InputModes.JIANPU]:
                possible_keys = myparser.find_key(song_lines)
                if len(possible_keys) == 0:
                    await channel.send("\nYour song cannot be transposed exactly in Sky.")
                    # trans = input('Enter a key or a number to transpose your song within the chromatic scale:')
                    await channel.send("\nDefault key will be set to C.")
                    song_key = 'C'
                elif len(possible_keys) == 1:
                    song_key = str(possible_keys[0])
                    await channel.send("\nYour song can be transposed in Sky with the following key: " + song_key)
                else:

                    await channel.send(
                        "\nYour song can be transposed in Sky with the following keys: " + ', '.join(possible_keys))

                    while song_key not in possible_keys:
                        song_key = await Questions.ask_text(self.bot, channel, ctx.author,
                                                            Lang.get_string("music/choose_key"),
                                                            validator=max_length(3))
            else:
                song_key = 'C'

            song_title = await Questions.ask_text(self.bot, channel, ctx.author,
                                                  Lang.get_string("music/song_title", max=200),
                                                  validator=max_length(200))

            if song_title == '':
                song_title = str(ctx.author) + 'untitled'  # TODO: generate random title to avoid clashes

            # Parses song line by line
            english_song_key = myparser.english_note_name(song_key)
            note_shift = 0
            mysong = Song(english_song_key)  # The song key must be in English format
            for song_line in song_lines:
                instrument_line = myparser.parse_line(song_line, song_key,
                                                      note_shift)  # The song key must be in the original format
                mysong.add_line(instrument_line)

            mysong.set_title(song_title)

            if RenderModes.PNG in ENABLED_MODES:
                png_path0 = os.path.join(SONG_DIR_OUT, song_title + '.png')
                file_count, png_path = mysong.write_png(png_path0)

                # upload attachments

                if png_path != '':
                    my_files = []

                    for file_idx in range(file_count + 1):

                        if file_idx == 0:
                            file_idx = ''
                        my_files.append(File(os.path.join(SONG_DIR_OUT, song_title + str(file_idx) + '.png')))

                await channel.send(files=my_files)

            if RenderModes.SKYASCII in ENABLED_MODES and song_notation not in [InputModes.SKY, InputModes.SKYKEYBOARD]:
                await channel.send('```\n' + mysong.write_ascii(RenderModes.SKYASCII) + '\n```')
            # await ctx.send(mysong.write_ascii(RenderModes.SKYASCII))

            await ctx.send("Song complete.")

        except Forbidden as ex:
            m.bot_cannot_dm_member.inc()
            await ctx.send(
                Lang.get_string("music/dm_unable", user=ctx.author.mention),
                delete_after=30)

        except asyncio.TimeoutError as ex:
            m.report_incomplete_count.inc()
            await channel.send(Lang.get_string("bugs/report_timeout"))
            if active_question is not None:
                m.reports_exit_question.observe(active_question)
            self.bot.loop.create_task(self.delete_progress(ctx.author.id))
        except CancelledError as ex:
            m.report_incomplete_count.inc()
            if active_question is not None:
                m.reports_exit_question.observe(active_question)
            if not restarting:
                raise ex
        except Exception as ex:
            self.bot.loop.create_task(self.delete_progress(ctx.author.id))
            await Utils.handle_exception("bug reporting", self.bot, ex)
            raise ex
        else:
            self.bot.loop.create_task(self.delete_progress(ctx.author.id))

        return


def setup(bot):
    bot.add_cog(Music(bot))
