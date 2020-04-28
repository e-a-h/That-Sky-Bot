import asyncio
import os
from concurrent.futures import CancelledError
import sys
import time
# from datetime import datetime

from discord import Forbidden, File, Reaction
from discord.ext import commands, tasks
from discord.ext.commands import Context, command

from cogs.BaseCog import BaseCog

from utils import Lang, Emoji, Questions, Utils, Configuration

try:
    music_maker_path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '../sky-python-music-sheet-maker'))
    if music_maker_path not in sys.path:
        sys.path.append(music_maker_path)
    from src.skymusic.communicator import Communicator, QueriesExecutionAbort
    from src.skymusic.music_sheet_maker import MusicSheetMaker
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
                return Lang.get_string("music/text_too_long", max=length)  # TODO: check that this string exists
            return True

        return real_check

    async def async_execute_queries(self, channel, user, queries=None):

        question_timeout = 5 * 60

        if queries is None:
            self.communicator.memory.clean()
            queries = self.communicator.recall_unsatisfied(filters=('to_me'))
        else:
            if not isinstance(queries, (list, set)):
                queries = [queries]

        for q in queries:
            reply_valid = False
            while not reply_valid:

                async def answer_number(first_number, i):
                    nonlocal answer_number
                    if isinstance(i, int):
                        answer_number = first_number + i
                    else:
                        answer_number = i
                
                query_dict = self.communicator.query_to_discord(q)

                options = [Questions.Option("QUESTION_MARK", 'Help', handler=answer_number, args=(None,'?'))]

                if 'options' in query_dict:
                    
                    if len(query_dict['options']) > 0 and len(query_dict['options']) <= 10:

                        reaction_choices = True
                        question_text = query_dict['question']
                        first_number = query_dict['options'][0]['number']
                        options = options + [Questions.Option("NUMBER_%d" % i, option['text'], handler=answer_number, args=(first_number,i))
                                   for i, option in enumerate(query_dict['options'])]
                    else:

                        reaction_choices = False
                        question_text = query_dict['result']

                else:
                    reaction_choices = False
                    question_text = query_dict['result']

                reply_valid = True  # to be sure to break the loop
                if q.get_expect_reply():
                    await channel.trigger_typing()

                    if reaction_choices:

                        await Questions.ask(bot=self.cog.bot, channel=channel, author=user, text=question_text,
                                            options=options, show_embed=True, delete_after=True)
                        answer = answer_number
                        
                    else:
                        
                        answer = await Questions.ask_text(self.cog.bot, channel, user,
                                                          question_text, timeout=question_timeout,
                                                          validator=self.max_length(2000))
                    if answer is not None:
                        q.reply_to(answer)
                        reply_valid = q.get_reply_validity()
                    # TODO: handle abort signals

                else:
                    message = await channel.send(question_text)
                    # TODO: add a wait? add something to seperate from next message anyway
                    if message is not None:
                        q.reply_to('ok')
                        reply_valid = q.get_reply_validity()

        return True

    async def send_song_to_channel(self, channel, user, song_bundle, song_title='Untitled'):

        # A song bundle is an objcet returning a dictionary of song meta data and a dict of IOString or IOBytes buffers, as lists indexed by their RenderMode
        await channel.trigger_typing()
        message = "Here are your song files(s)"
        
        song_renders = song_bundle.get_all_renders()
        
        for render_mode, buffers in song_renders.items():
            my_files = [File(buffer, filename='%s_%d%s' % (song_title, i, render_mode.extension))
                        for (i, buffer) in enumerate(buffers)]
            if len(my_files) > 10:
                my_files = my_files[:9]
                message += ". Sorry, I wasn't allowed to send you more than 10 files."
            await channel.send(content=message, files=my_files)


class Music(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.in_progress = dict()  # {user_id: asyncio_task}

    # TODO: create methods to update the bot metrics and in_progress, etc

    async def delete_progress(self, user):
        uid = user.id
        if uid in self.in_progress:
            self.in_progress[uid].cancel()
            del self.in_progress[uid]

    '''
    async def delete_progress_delayed(self, user):
        delete_timeout = 10*60
        await asyncio.sleep(delete_timeout)
        if user.id in self.in_progress:
            if not self.in_progress[user.id].done() or not self.in_progress[user.id].cancelled():
                await user.send(Lang.get_string("music/song_trash"))

            await self.delete_progress(user.id)

    '''

    # @commands.group(name='song', invoke_without_command=True)

    @commands.command(aliases=['song'])
    async def transcribe_song(self, ctx: Context):

        if ctx.guild is not None:
            await ctx.message.delete()  # remove command to not flood chat (unless we are in a DM already)

        user = ctx.author

        if user.id in self.in_progress:

            starting_over = False

            async def start_over():
                nonlocal starting_over
                starting_over = True

            # ask if user wants to start over
            await Questions.ask(bot=self.bot, channel=ctx.channel, author=user,
                                text=Lang.get_string("music/start_over", user=user.mention),
                                options=[
                                    Questions.Option("YES", Lang.get_string("music/start_over_yes"),
                                                     handler=start_over),
                                    Questions.Option("NO", Lang.get_string("music/start_over_no"))
                                ],
                                show_embed=True, delete_after=True)

            if not starting_over:
                return  # in-progress report should not be reset. bail out

            await self.delete_progress(user)

        # Start a song creation
        task = self.bot.loop.create_task(self.actual_transcribe_song(user, ctx))
        self.in_progress[user.id] = task
        try:
            await task
        except CancelledError as ex:
            pass

    # @commands.command(aliases=['song'])
    async def actual_transcribe_song(self, user, ctx):

        active_question = None

        try:
            # starts a dm
            channel = await user.create_dm()
            asking = True

            if not asking:
                return
            else:

                active_question = 0

                player = MusicCogPlayer(cog=self, locale='en_US')
                maker = MusicSheetMaker(locale='en_US')

                # 1. Set Song Parser
                maker.set_song_parser()

                # 2. Display instructions
                i_instr, _ = maker.ask_instructions(recipient=player, execute=False)
                answered = await player.async_execute_queries(channel, user, i_instr)
                # result = i_instr.get_reply().get_result()
                active_question += 1

                #2.c
                q_aspect, _ = maker.ask_aspect_ratio(recipient=player, prerequisites=[i_instr],
                                                                execute=False)
                answered = await player.async_execute_queries(channel, user, q_aspect)
                aspect_ratio = q_aspect.get_reply().get_result()
                active_question += 1

                # 3. Ask for notes
                # TODO: allow the player to enter the notes using several messages??? or maybe not
                q_notes, _ = maker.ask_notes(recipient=player, prerequisites=[i_instr], execute=False)
                answered = await player.async_execute_queries(channel, user, q_notes)
                notes = q_notes.get_reply().get_result()
                active_question += 1

                # 4. Ask for input mode (or display the one found)
                q_mode, input_mode = maker.ask_input_mode(recipient=player, notes=notes, prerequisites=[q_notes],
                                                          execute=False)
                answered = await player.async_execute_queries(channel, user, q_mode)
                if input_mode is None:
                    input_mode = q_mode.get_reply().get_result()
                active_question += 1

                # 5. Set input_mode
                maker.set_parser_input_mode(recipient=player, input_mode=input_mode)
                active_question += 1

                # 6. Ask for song keye (or display the only one possible)
                (q_key, song_key) = maker.ask_song_key(recipient=player, notes=notes, input_mode=input_mode,
                                                       prerequisites=[q_notes, q_mode], execute=False)
                answered = await player.async_execute_queries(channel, user, q_key)
                if song_key is None:
                    song_key = maker.retrieve_song_key(recipient=player, notes=notes, input_mode=input_mode)
                    # song_key = q_mode.get_reply().get_result()
                active_question += 1

                # 7. Asks for octave shift
                q_shift, _ = maker.ask_octave_shift(recipient=player, execute=False)
                answered = await player.async_execute_queries(channel, user, q_shift)
                octave_shift = q_shift.get_reply().get_result()
                active_question += 1

                # 8. Parse song
                maker.parse_song(recipient=player, notes=notes, song_key=song_key, octave_shift=octave_shift)
                active_question += 1

                # 9. Displays error ratio
                i_error, _ = maker.display_error_ratio(recipient=player, prerequisites=[q_notes, q_mode, q_shift],
                                                       execute=False)
                answered = await player.async_execute_queries(channel, user, i_error)
                active_question += 1

                # 10. Asks for song metadata
                qs_meta, _ = maker.ask_song_metadata(recipient=player, execute=False)
                answered = await player.async_execute_queries(channel, user, qs_meta)
                (title, artist, transcript) = [q.get_reply().get_result() for q in qs_meta]
                maker.get_song().set_meta(title=title, artist=artist, transcript=transcript, song_key=song_key)
                active_question += 1

                # 11. Renders Song
                song_bundle = await asyncio.get_event_loop().run_in_executor(None, maker.render_song, player, None, aspect_ratio)

                await player.send_song_to_channel(channel, user, song_bundle, title)
                active_question += 1

                self.bot.loop.create_task(self.delete_progress_delayed(user))

        except Forbidden as ex:
            await ctx.send(
                Lang.get_string("music/dm_unable", user=user.mention),
                delete_after=30)
        except asyncio.TimeoutError as ex:
            await channel.send(Lang.get_string("music/song_timeout"))
            self.bot.loop.create_task(self.delete_progress(user))
        except CancelledError as ex:
            raise ex
        except Exception as ex:
            self.bot.loop.create_task(self.delete_progress(user))
            await Utils.handle_exception("song creation", self.bot, ex)
        else:
            self.bot.loop.create_task(self.delete_progress(user))

        return


"""
    @commands.command(aliases=['song_tutorial'])
    async def song_tutorial(self, ctx):

        m = self.bot.metrics
        active_question = None
        restarting = False

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

            # Tutorial code here
"""

"""
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        #react_user_id = event.user_id
        channel = self.bot.get_channel(event.channel_id)
       # message = await channel.fetch_message(event.message_id)
        user_is_bot = event.user_id == self.bot.user.id
        #rules_message_id = Configuration.get_var('rules_react_message_id')
        if not user_is_bot:
            #await self.handle_reaction_change("add", str(event.emoji), react_user_id)
            await channel.send("Sorry to see you go. Goodbye!")  #TODO music/goodbye
            #TODO: stop the transcribe song process. how? change self.property?
"""


def setup(bot):
    bot.add_cog(Music(bot))
