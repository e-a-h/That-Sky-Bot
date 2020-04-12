import asyncio
import os
from concurrent.futures import CancelledError
import sys

from discord import Forbidden, File
from discord.ext import commands

from cogs.BaseCog import BaseCog

from utils import Lang, Emoji, Questions, Utils, Configuration


try:
    music_maker_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),'sky-python-music-sheet-maker/python/'))
    if music_maker_path not in sys.path:
        sys.path.append(music_maker_path) 
    # from modes import InputMode, RenderMode, CSSMode

    # from songparser import SongParser
    # from song import Song
    from communicator import Communicator, QueriesExecutionAbort
    from music_sheet_maker import MusicSheetMaker
except ImportError as e:
    print('*** IMPORT ERROR of one or several Music-Maker modules')
    print(e)


class MusicCogPlayer:

    def __init__(self, cog, locale='en_US'):
        self.cog = cog
        self.name = 'music-cog'  # Must be defined before instanciating communicator
        self.locale = locale
        self.communicator = Communicator(owner=self, locale=locale)

    def get_name(self):
        return self.name

    def get_locale(self):        
        return self.locale

    def receive(self, *args, **kwargs):
        self.communicator.receive(*args, **kwargs)

    def max_length(self, length):
        def real_check(text):
            if len(text) > length:
                return Lang.get_string("music/text_too_long", max=length) #TODO: check that this string exists
            return True

        return real_check

    async def async_execute_queries(self, channel, ctx, queries=None):

        if queries is None:
            self.communicator.memory.clean()
            queries = self.communicator.recall_unsatisfied(filters=('to_me'))
        else:
            if not isinstance(queries, (list, set)):
                queries = [queries]

        for q in queries:
            reply_valid = False
            while not reply_valid:
                question = self.communicator.query_to_discord(q)
                reply_valid = True  # to be sure to break the loop
                if q.get_expect_reply():
                    answer = await Questions.ask_text(self.cog.bot, channel, ctx.author,
                                                      question,
                                                      validator=self.max_length(2000))
                    # TODO: handle abort signals
                    q.reply_to(answer)
                    reply_valid = q.get_reply_validity()
                else:
                    await channel.send(question)
                    q.reply_to('ok')
                    reply_valid = q.get_reply_validity()

        return

    async def send_song_to_channel(self, channel, ctx, song_bundle, song_title='Untitled'):

        # A song bundle is a list of tuples
        # Each tuple is made of a list of buffers and a list of corresponding modes
        # Each buffer is an IOString or IOBytes object
        message = "Here are your song files(s)"

        for (buffers, render_modes) in song_bundle:
            my_files = [File(buffer, filename='%s_%d%s' % (song_title, i, render_mode.extension)) for
                        (i, buffer), render_mode in zip(enumerate(buffers), render_modes)]
            if len(my_files) > 10:
                my_files = my_files[:9]
                message += ". Sorry, I wasn't allowed to send you more than 10 files."
            # TODO: handle more than 10 files
            await channel.send(content=message, files=my_files)


class Music(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
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

    '''
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        react_user_id = event.user_id
        channel = self.bot.get_channel(event.channel_id)
        message = await channel.fetch_message(event.message_id)
        user_is_bot = event.user_id == self.bot.user.id
        #rules_message_id = Configuration.get_var('rules_react_message_id')
        if not user_is_bot:
            await self.handle_reaction_change("add", str(event.emoji), react_user_id)
            print(channel)
            print(react_user_id)
            print(message)
    '''
       
 #await self.report_bug(user, channel)
 
    @commands.command(aliases=['ts', 'song'])
    async def transcribe_song(self, ctx):

        m = self.bot.metrics
        active_question = None
        restarting = False

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

            player = MusicCogPlayer(cog=self, locale='en_US')
            maker = MusicSheetMaker(locale='en_US')

            #DEBUG
            await Questions.ask(self.bot, channel, ctx.author, Lang.get_string("bugs/question_ready"),
                    [
                        Questions.Option("YES", "Press this reaction to answer YES and begin a Song"),
                        Questions.Option("NO", "Press this reaction to answer NO and abort", handler=abort),
                    ], show_embed=True)


            # 1. Set Song Parser
            maker.set_song_parser()

            # 2. Display instructions
            i_instr, _ = maker.ask_instructions(recipient=player, execute=False)
            await player.async_execute_queries(channel, ctx, i_instr)
            # result = i_instr.get_reply().get_result()

            # 3. Ask for notes
            # TODO: allow the player to enter the notes using several messages??? or maybe not
            q_notes, _ = maker.ask_notes(recipient=player, prerequisites=[i_instr], execute=False)
            await player.async_execute_queries(channel, ctx, q_notes)
            notes = q_notes.get_reply().get_result()

            # 4. Ask for input mode (or display the one found)
            q_mode, input_mode = maker.ask_input_mode(recipient=player, notes=notes, prerequisites=[q_notes],
                                                      execute=False)
            await player.async_execute_queries(channel, ctx, q_mode)
            if input_mode is None:
                input_mode = q_mode.get_reply().get_result()

            # 5. Set input_mode
            maker.set_parser_input_mode(recipient=player, input_mode=input_mode)

            # 6. Ask for song keye (or display the only one possible)
            (q_key, song_key) = maker.ask_song_key(recipient=player, notes=notes, input_mode=input_mode,
                                                   prerequisites=[q_notes, q_mode], execute=False)
            await player.async_execute_queries(channel, ctx, q_key)
            if song_key is None:
                song_key = maker.retrieve_song_key(recipient=player, notes=notes, input_mode=input_mode)
                # song_key = q_mode.get_reply().get_result()

            # 7. Asks for octave shift
            q_shift, _ = maker.ask_octave_shift(recipient=player, execute=False)
            await player.async_execute_queries(channel, ctx, q_shift)
            octave_shift = q_shift.get_reply().get_result()

            # 8. Parse song
            maker.parse_song(recipient=player, notes=notes, song_key=song_key, octave_shift=octave_shift)

            # 9. Displays error ratio
            i_error, _ = maker.display_error_ratio(recipient=player, prerequisites=[q_notes, q_mode, q_shift],
                                                   execute=False)
            await player.async_execute_queries(channel, ctx, i_error)
            # error_message = i_error.get_reply().get_result()

            # 10. Asks for song metadata
            qs_meta, _ = maker.ask_song_metadata(recipient=player, execute=False)
            await player.async_execute_queries(channel, ctx, qs_meta)
            (title, artist, transcript) = [q.get_reply().get_result() for q in qs_meta]
            maker.get_song().set_meta(title=title, artist=artist, transcript=transcript, song_key=song_key)

            # 11. Renders Song
            song_bundle = maker.render_song(recipient=player)
            await player.send_song_to_channel(channel, ctx, song_bundle, title)


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
