import yaml
import random

import discord
from discord import app_commands, Interaction, InteractionType, ComponentType, Permissions
import discord.ext.commands as MessageCommands

import os
import sys
from utils import Logging

try:
    pwd = os.path.dirname(os.path.realpath(__file__))
    dialoger_path = os.path.normpath(os.path.join(pwd, '../Discordpy-Dialogs'))
    if not os.path.isdir(dialoger_path):
        dialoger_path = os.path.normpath(os.path.join(pwd, '../../Discordpy-Dialogs'))
    if dialoger_path not in sys.path:
        sys.path.append(dialoger_path)
    Logging.info(sys.path)
    import src.DialogHandler as DialogHandler
    import Examples.Discord.DiscordUtils as DiscordUtils
    import Examples.Discord.DiscordMessagingFuncs as DialogDiscordBaseFuncs
    import cogConfig.Admin.AdminFunctions as AdminFunctions
    # for writing callbacks
    import src.utils.callbackUtils as cbUtils
    from src.utils.Enums import POSSIBLE_PURPOSES

    from src.utils.Cache import Cache, CollectionIndex, Index, CacheEntry, COPY_RULES
except ImportError as e:
    Logging.info('*** IMPORT ERROR of one or several Dialoger')
    Logging.info(e)


import cogs.BaseCog as BaseCog


# Trivia questions data fields relations
#       each question has an id
#       each question can be in multiple collections
#           all questions technically part of a default collection but not really fun to list that
#

#TODO: migrate to SQL, how app command syncing will work

class CompleteEntries(Index):
    '''index that tracks if entries are complete or not based off of if entries have certain data fields or not'''
    def __init__(self, name, req_fields=None) -> None:
        super().__init__(name)
        self.req_fields = set(req_fields) if req_fields is not None else set()

    def assure_sets(self):
        '''assure structures are set up'''
        if "incomplete" not in self.pointers:
            self.pointers["incomplete"] = set()
        if "complete" not in self.pointers:
            self.pointers["complete"] = set()
        if "empty" not in self.pointers:
            self.pointers["empty"] = set()

    def get(self, key, default=None):
        self.assure_sets()
        return super().get(key, default)

    def add_entry(self, primary_key, to_add_values):
        self.assure_sets()
        num_found = 0
        for req_field in self.req_fields:
            if req_field in to_add_values:
                num_found += 1
        if num_found == 0:
            self.pointers["empty"].add(primary_key)
        elif num_found == len(self.req_fields):
            self.pointers["complete"].add(primary_key)
        else:
            self.pointers["incomplete"].add(primary_key)

    def update_entry(self, primary_key, to_update_values):
        cache_entry = self.cache.data[primary_key]
        key_set = set(cache_entry.data.keys())
        for key in to_update_values:
            key_set.add(key)

        num_found = 0
        for req_field in self.req_fields:
            if req_field in key_set:
                num_found += 1
        if num_found == 0:
            final_set = "empty"
        elif num_found == len(self.req_fields):
            final_set = "complete"
        else:
            final_set = "incomplete"

        for s in ["empty", "complete", "incomplete"]:
            if s == final_set:
                self.pointers[s].add(primary_key)
            elif primary_key in self.pointers[s]:
                self.pointers[s].remove(primary_key)


    def del_entry(self, primary_key, cache_entry: CacheEntry):
        if primary_key in self.pointers["incomplete"]:
            self.pointers["incomplete"].remove(primary_key)
        elif primary_key in self.pointers["complete"]:
            self.pointers["complete"].remove(primary_key)
        elif primary_key in self.pointers["empty"]:
            self.pointers["empty"].remove(primary_key)

class Trivia(BaseCog.BaseCog):
    def __init__(self, bot):
        super().__init__(bot)

        # handler for the actual Trivia question posts
        self.trivia_qs_handler = DialogHandler.DialogHandler(bot=bot)
        self.trivia_qs_handler.setup_from_files(["cogConfig/Trivia/TriviaGraph.yml"])
        self.trivia_qs_handler.register_module(DialogDiscordBaseFuncs)
        self.trivia_qs_handler.register_functions({self.store_trivia_start_input:{},
                                                   self.choose_random_trivia_q:{},
                                                   self.send_trivia_q:{},
                                                   self.tally_trivia_button_response:{},
                                                   self.trivia_is_answered:{},
                                                   self.close_trivia_q:{}})

        # store for question info
        self.trivia_qs = Cache(secondaryIndices=[CollectionIndex("collections", "collections"),
                                                 CompleteEntries("completeness", req_fields=["question", "answers", "options"])])
        self.trivia_collections = Cache(secondaryIndices=[CollectionIndex("questions", "questions")])
        # WIP to allow channels to be places where trivia will randomly from time to time drop
        #self.random_trivia_channels = dict()
        # trigger trivia in channel command
        # random trivia send task

        # add on the graph info for managing the settings for this cog
        #TODO: these nodes WIP, need new home for skybot
        self.trivia_admin_handler = DialogHandler.DialogHandler(bot=bot)
        self.trivia_admin_handler.add_files(["cogConfig/Trivia/TriviaAdminGraph.yml"])
        self.trivia_admin_handler.register_module(AdminFunctions)
        self.trivia_admin_handler.register_module(DialogDiscordBaseFuncs)
        self.trivia_admin_handler.register_functions({self.show_server_trivia_config:{}, self.show_server_qs_config:{}})

    async def notify_handlers(self, event_name, event):
        await self.trivia_qs_handler.notify_event(event_name, event)
        await self.trivia_admin_handler.notify_event(event_name, event)

    @MessageCommands.Cog.listener()
    async def on_interaction(self, interaction):
        # NOTE: discord.py comes with views to handle interaction components on messages, but we're overriding those and handling it ourselves
        #       because during designing there was a bug where different view objects with components with same name would get confused.
        print(f"bot on interaction entry point, interaction is <{interaction}>, type is <{interaction.type}> data is <{interaction.data}> response done? <{interaction.response.is_done()}>")
        
        if interaction.type == InteractionType.component:
            if interaction.data["component_type"] == ComponentType.button.value:
                await self.notify_handlers("button_click", interaction)
            if interaction.data["component_type"] == ComponentType.select.value:
                await self.notify_handlers("select_menu", interaction)
        elif interaction.type == InteractionType.application_command:
            await self.notify_handlers("application_command", interaction)
        elif interaction.type == InteractionType.modal_submit:
            await self.notify_handlers("modal_submit", interaction)

    async def on_ready(self):
        await self.bot.wait_until_ready()
        self.trivia_admin_handler.final_validate()
        self.trivia_qs_handler.final_validate()
        self.load_trivia_data()

    def cog_load(self):
        self.trivia_qs_handler.start_cleaning()
        self.trivia_admin_handler.start_cleaning()

    def cog_unload(self):
        self.trivia_qs_handler.stop_cleaning()
        self.trivia_admin_handler.stop_cleaning()

    def load_trivia_data(self):
        '''clears cache and loads what questions are avialable and their groupings into collections'''
        #TODO: moify for SQL
        self.trivia_qs.clear()
        self.trivia_collections.clear()

        with open("cogConfig/Trivia/trivia_qs_collections.yml") as file:
            # load mapping of question to collection(s) it is in
            id_collection_mapping = yaml.safe_load(file)
            for mapping_entry in id_collection_mapping:
                q_id = mapping_entry["id"]
                collections = mapping_entry["collections"]
                if type(collections) is str:
                    collections = [collections]

                if q_id in self.trivia_qs:
                    # if a question was listed twice, update its collections list. can't use cache.update since that only
                    # works on top level keys and will overwrite the collection set. so grab a direct reference to data
                    entry_data = self.trivia_qs.get(q_id, override_copy_rule=COPY_RULES.ORIGINAL)[0]
                    for collection in collections:
                        entry_data["collections"].add(collection)
                        # diret messing with data doesn't update indices, so tell it to do that
                        self.trivia_qs.reindex(updated_keys=q_id)
                else:
                    data = {"id":q_id, "collections":set()}
                    for collection in collections:
                        data["collections"].add(collection)
                    self.trivia_qs.update(q_id, data)

                for collection in collections:
                    if collection in self.trivia_collections:
                        entry_data = self.trivia_collections.get(collection, override_copy_rule=COPY_RULES.ORIGINAL)[0]
                        entry_data["questions"].add(q_id)
                        self.trivia_collections.reindex(updated_keys=collection)
                    else:
                        self.trivia_collections.update(collection, {"collection": collection, "questions":set([q_id])})

        # load actual question content and settings
        with open("cogConfig/Trivia/en_US_trivia_Qs.yml") as file:
            yaml_questions = yaml.safe_load(file)
            for yaml_question in yaml_questions:
                data = {"id": yaml_question["id"]}
                if "q" in yaml_question:
                    data["question"] = yaml_question["q"]
                if "a" in yaml_question:
                    data["answers"] =  [yaml_question["a"]] if type(yaml_question["a"]) is str else yaml_question["a"]
                if "o" in yaml_question:
                    data["options"] = yaml_question["o"]
                self.trivia_qs.update(yaml_question["id"], data)

    '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #       COMMANDS
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''

    triva_app_cmd_root_group = app_commands.Group(name="trivia", default_permissions=Permissions(ban_members=True), description="config for trivia", guild_ids=[621746949485232154, 872341812541526017])
    trivia_editing_group = app_commands.Group(name = "config", parent=triva_app_cmd_root_group, description="all configuration modification")

    @MessageCommands.command()
    async def trivia_config(self, ctx: MessageCommands.Context):
        await self.trivia_admin_handler.start_at("server_trivia_config", "message_command", ctx)

    @triva_app_cmd_root_group.command()
    @app_commands.describe(channel='channel to send trivia in', question="id of trivia question to send")
    async def stump_me(self, interaction:Interaction, question: str=None, channel: discord.TextChannel=None):
        if channel is not None:
            interaction.extras["dest_channel"] = channel
        if question is not None:
            interaction.extras["question"] = question
        await self.trivia_qs_handler.start_at("question", "application_command", interaction)

    @trivia_editing_group.command()
    @app_commands.describe(id="unique short alphanumric id for question", question="text for the actual question",
                           answers="comma separated list of accepted answers", options="comma separated lists of response options",
                           collections="comma separated list of collections question is in")
    async def create_question(self, interaction:Interaction, id:str, question:str, answers:str, options:str, collections:str=None):
        if id in self.trivia_qs and id not in self.trivia_qs.get_key("empty", index_name="completeness", default=[]):
            # don't want to override a question that's already got data
            await interaction.response.send_message(content="there's a question with that id, try edit instead", ephemeral=True)
            return
        self.update_question(id=id, question=question, answers=answers, options=options, collections=collections)
        field = self.get_trivia_q_embed_field_display(id, detail_level=3)
        if field is None:
            await interaction.response.send_message(content=f"failed to create question {id}")
        else:
            await interaction.response.send_message(content=f"question {id} created", embed=DiscordUtils.build_embed({"fields":[field]}))

    @trivia_editing_group.command()
    @app_commands.describe(id="unique short alphanumric id for question")
    async def get_question(self, interaction:Interaction, id:str):
        field = self.get_trivia_q_embed_field_display(id, detail_level=3)
        if field is None:
            await interaction.response.send_message(content=f"no trivia question found with id {id}", ephemeral=True)
        else:
            await interaction.response.send_message(content=f"question {id} details", embed=DiscordUtils.build_embed({"fields":[field]}))

    @trivia_editing_group.command()
    @app_commands.describe(id="unique short alphanumric id for question", question="text for the actual question",
                           answers="comma separated list of accepted answers", options="comma separated lists of response options",
                           collections="comma separated list of collections question is in")
    async def edit_question(self, interaction:Interaction, id:str, question:str=None, answers:str=None, options:str=None, collections:str=None):
        update_res = self.update_question(id=id, question=question, answers=answers, options=options, collections=collections)
        field = self.get_trivia_q_embed_field_display(id, detail_level=3)
        if update_res is None:
            await interaction.response.send_message(content=f"failed to update question {id}")
        else:
            await interaction.response.send_message(content=f"question {id} updated", embed=DiscordUtils.build_embed({"fields":[field]}))

    @trivia_editing_group.command()
    @app_commands.describe(id="unique short alphanumric id for question")
    async def delete_question(self, interaction:Interaction, id:str):
        # field would be good if wanting to display the question just deleted, but also serves the task of checking if question is real
        field = self.get_trivia_q_embed_field_display(id, detail_level=3)
        if field is None:
            await interaction.response.send_message(content=f"question {id} not found")
        self.trivia_qs.delete(key=id, index_name="primary")
        if id in self.trivia_collections.get_key(key=id, index_name="questions", default=[]):
            for collection in self.trivia_collections.get_key(key=id, index_name="questions"):
                entry = self.trivia_collections.get(key=collection, index_name="primary", override_copy_rule=COPY_RULES.ORIGINAL)
                entry.data["questions"].remove[collection]
                self.trivia_collections.reindex(collection)
        self.save_trivia()
        await interaction.response.send_message(content=f"question {id} deleted")

    @trivia_editing_group.command()
    @app_commands.describe(collection="collection name", questions="comma separated list of question ids to add to collection")
    async def create_collection(self, interaction:Interaction, collection:str, questions:str=None):
        if collection in self.trivia_collections:
            await interaction.response.send_message(content="there's a collection with that id, try edit instead", ephemeral=True)
            return
        self.update_collections(collection, questions)

        field = self.get_trivia_collec_embed_field_display(collection, detail_level=3)
        if field is None:
            await interaction.response.send_message(content=f"collection creation failed", ephemeral=True)
        else:
            await interaction.response.send_message(content="collection created", embed=DiscordUtils.build_embed({"fields":[field]}))

    @trivia_editing_group.command()
    @app_commands.describe(collection="collection name")
    async def get_collection(self, interaction:Interaction, collection:str):
        field = self.get_trivia_collec_embed_field_display(collection, detail_level=3)
        if field is None:
            await interaction.response.send_message(content=f"no trivia collection found with name {collection}", ephemeral=True)
        else:
            await interaction.response.send_message(content=f"collection named {collection} details", embed=DiscordUtils.build_embed({"fields":[field]}))
    
    @trivia_editing_group.command()
    @app_commands.describe(collection="collection name", questions="comma separated list of question ids to add to collection")
    async def edit_collection(self, interaction:Interaction, collection:str, questions:str=None):
        update_res = self.update_collections(collection=collection, questions=questions)
        field = self.get_trivia_collec_embed_field_display(collection, detail_level=3)
        if update_res is None:
            await interaction.response.send_message(content=f"failed to update collection {collection}")
        else:
            await interaction.response.send_message(content=f"collection {collection} updated", embed=DiscordUtils.build_embed({"fields":[field]}))

    @trivia_editing_group.command()
    @app_commands.describe(collection="collection name")
    async def delete_collection(self, interaction:Interaction, collection:str):
        field = self.get_trivia_collec_embed_field_display(collection, detail_level=3)
        if field is None:
            await interaction.response.send_message(content=f"collection {collection} not found")
        self.trivia_collections.delete(key=collection,index_name="primary")
        self.save_trivia()
        
        await interaction.response.send_message(content=f"collection {collection} deleted")
    #TODO: disable question, disable collection, list views, search, clean lists

    '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #       DATA HANDLING
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''

    def update_question(self, id:str, question:str=None, answers:str=None, options:str=None, collections:str=None):
        '''parse input and update question data stores'''
        question_settings = {"id": id}
        if collections is not None:
            question_settings["collections"] = set()
            collections_list = collections.split(",")
            for collection in collections_list:
                question_settings["collections"].add(collection.strip())
        if question is not None:
            question_settings["question"] = question
        if answers is not None:
            question_settings["answers"] = set()
            answers_list = answers.split(",")
            for answer in answers_list:
                question_settings["answers"].add(answer.strip())
            question_settings["answers"] = list(question_settings["answers"])
        if options is not None:
            question_settings["options"] = set()
            options_list = options.split(",")
            for option in options_list:
                question_settings["options"].add(option.strip())
            question_settings["options"] = list(question_settings["options"])

        entry = self.trivia_qs.update(id, question_settings, index_name='primary', or_create=True)
        if entry is not None:
            for collection in question_settings.get("collections", []):
                # want to keep collections list up to date with whatever changes here
                if collection in self.trivia_collections:
                    entry_data = self.trivia_collections.get(collection, override_copy_rule=COPY_RULES.ORIGINAL)[0]
                    if "questions" in entry_data:
                        entry_data["questions"].add(id)
                        self.trivia_collections.reindex(key=collection)
                    else:
                        self.trivia_collections.update(collection, {"collection": collection, "questions":set([id])})
                else:
                    self.trivia_collections.update(collection, {"collection": collection, "questions":set([id])})
            self.save_trivia()
        return entry

    def update_collections(self, collection, questions:str):
        collection_settings = {"collection": collection}
        if questions is not None:
            collection_settings["questions"] = set()
            questions_list = questions.split(",")
            for question in questions_list:
                collection_settings["questions"].add(question.strip())

        entry = self.trivia_collections.update(collection, collection_settings, or_create=True)
        if entry is not None:
            for q_id in collection_settings.get("questions", []):
                if q_id in self.trivia_qs:
                    # if a question was listed twice, update its collections list. can't use cache.update since that only
                    # works on top level keys and will overwrite the collection set. so grab a direct reference to
                    entry_data = self.trivia_qs.get(q_id, override_copy_rule=COPY_RULES.ORIGINAL)[0]
                    if "collections" in entry_data:
                        entry_data["collections"].add(collection)
                        self.trivia_qs.reindex(updated_keys=q_id)
                    else:
                        data = {"id":q_id, "collections":set([collection])}
                        self.trivia_qs.update(q_id, data)
                else:
                    data = {"id":q_id, "collections":set([collection])}
                    self.trivia_qs.update(q_id, data)
            self.save_trivia()
        return entry

    def save_trivia(self):
        yaml_qs = []
        yaml_collections = []
        for id, entry in self.trivia_qs:
            if "collections" in entry.data:
                yaml_collections.append({"id": id, "collections": list(entry.data["collections"])})
            question_data = {"id": id}
            if "question" in entry.data:
                question_data.update({"q": entry.data["question"]})
            if "answers" in entry.data:
                question_data.update({"a": list(entry.data["answers"])})
            if "options" in entry.data:
                question_data.update({"o":list(entry.data["options"])})
            yaml_qs.append(question_data)

        with open("cogConfig/Trivia/en_US_trivia_Qs.yml", "w") as file:
            yaml.safe_dump(yaml_qs, file)

        with open("cogConfig/Trivia/trivia_qs_collections.yml", "w") as file:
            yaml.safe_dump(yaml_collections, file)

    '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #       GET DISPLAY FORMATS
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''

    def get_trivia_q_embed_field_display(self, q_id, detail_level=1):
        entry = self.trivia_qs.get(q_id, default=None)
        if entry is None:
            return None
        entry = entry[0]
        if detail_level == 1:
            return {
                "name": f"trivia question: {q_id}",
                "value": (f"**question**: {entry['question']}\n" if "question" in entry else "") +\
                            (f"**answers**: {', '.join(entry['answers'])}\n" if "answers" in entry else "") + \
                            (f"**options**: {', '.join(entry['options'])}\n" if "options" in entry else "")
            }
        elif detail_level == 2:
            return {
                "name": f"trivia question: {q_id}",
                "value": (f"**question**: {entry['question']}\n" if "question" in entry else "") +\
                            (f"**answers**: {', '.join(entry['answers'])}\n" if "answers" in entry else "") + \
                            (f"**options**: {', '.join(entry['options'])}\n" if "options" in entry else "") +\
                            (f"**collections**: {', '.join(entry['collections'])}" if "collections" in entry else "")
            }
        return {
            "name": f"trivia question: {q_id}",
            "value":(f"**ready to use?** {q_id in self.trivia_qs.get_key('complete', index_name='completeness')}\n") +\
                    (f"**question**: {entry['question']}\n" if "question" in entry else "") +\
                    (f"**answers**: {', '.join(entry['answers'])}\n" if "answers" in entry else "") + \
                    (f"**options**: {', '.join(entry['options'])}\n" if "options" in entry else "") +\
                    (f"**collections**: {', '.join(entry['collections'])}" if "collections" in entry else "")
        }

    def get_trivia_collec_embed_field_display(self, collection, detail_level=1):
        entry = self.trivia_collections.get(collection, default=None)
        if entry is None:
            return None
        entry = entry[0]
        if detail_level == 1:
            return {
                "name": f"trivia collection: {collection}",
                "value": (f"**questions**: {len(entry['questions'])}\n" if "question" in entry else "")
            }
        elif detail_level == 2:
            return {
                "name": f"trivia collection: {collection}",
                "value": (f"**questions**: {', '.join(entry['questions'])}\n" if "question" in entry else "")
            }
        else:
            return {
                "name": f"trivia collection: {collection}",
                "value": (f"**questions**: {', '.join(entry['questions'])}\n" if "question" in entry else "")
            }

    '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #       ADMIN HANDLING CALLBACKS
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''

    @cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
    async def show_server_trivia_config(self, active_node, event):
        handler = self.trivia_qs_handler
        header_string = f"settings for server id {active_node.session.data['origin_server'].id} and Trivia cog"
        embed_settings = {"fields":[{"name": "trivia questions loaded", "value": len(self.trivia_qs)},
                                    {"name": "collections", "value": len(self.trivia_collections)},
                                    {"name": "ongoing trivia", "value": str(len(handler.active_nodes))},
                                    {"name": "question cleaning status", "value": handler.cleaning_status["state"].name}]}
        component_settings = [
            {"type":"Button", "custom_id":"show_trivia_qs", "label":"configure questions"},
            {"type":"Button", "custom_id":"show_trivia_channels", "label":"coming later", "disabled":True}
            ]
        await DialogDiscordBaseFuncs.send_message(active_node, event, {"message":{"content":header_string, "components":component_settings, "embed":embed_settings}, "menu":True})

    @cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
    async def show_server_qs_config(self, active_node, event):
        if not hasattr(active_node, "display_page"):
            AdminFunctions.setup_paging(active_node, self.trivia_qs.data, self.trivia_qs.data)

        fields = []
        print(f"showing questions, ids on page {active_node.display_page} are {active_node.pages[active_node.display_page]}")
        for q_id in active_node.pages[active_node.display_page]:
            field = self.get_trivia_q_embed_field_display(q_id, detail_level=2)
            if field is None:
                print(f"question id'd {q_id} does not exist. skipping")
                continue
            fields.append(field)

        embed_settings = {"fields":fields}
        component_settings = [
            {"type":"Button", "custom_id":"prev_page", "label":"prev page", "disabled": len(active_node.pages) == 1},
            {"type":"Button", "custom_id":"next_page", "label":"next page", "disabled": len(active_node.pages) == 1}
        ]
        await DialogDiscordBaseFuncs.edit_message(active_node, event, {"message":{"components":component_settings, "embed":embed_settings}, "menu":True})
    '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #       TRIVIA CALLBACKS
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''

    # data stored on node:
    #       trivia_question - a copy of the settings of trivia question that this node is sending
    #       tally - tallys set of userids that voted for each option of the trivia question
    #       dest_channel - channel trivia question was sent to
    #       max_correct_answers -


    @cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION], has_parameter="always")
    def store_trivia_start_input(self, active_node, event, event_name):
        '''callback that takes graph start events and stores info about the trivia question that this node will be sending'''
        if event_name == "application_command":
            if "question" in event.extras and event.extras["question"] in self.trivia_qs and \
                    event.extras['question'] in self.trivia_qs.get_key("complete", index_name="completeness"):
                # only select question if it is loaded in trivia questions and marked as complete
                active_node.trivia_question = self.trivia_qs.get(event.extras["question"], override_copy_rule=COPY_RULES.DEEP)[0]
            if "dest_channel" in event.extras:
                active_node.dest_channel = event.extras["dest_channel"]
        elif event_name == "trivia_time":
            #TODO: WIP, and uncomment in graph when ready
            pass

    @cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
    def choose_random_trivia_q(self, active_node, event):
        '''fill in choice of trivia question to send if missing and final setup of answer tally'''
        if not hasattr(active_node,"trivia_question") or not active_node.trivia_question["id"] in self.trivia_qs or not \
                active_node.trivia_question["id"] in self.trivia_qs.get_key("complete", index_name="completeness"):
            good_to_go_qs = self.trivia_qs.get("complete", index_name="completeness", override_copy_rule=COPY_RULES.DEEP)
            active_node.trivia_question = random.choice(good_to_go_qs)
        active_node.tally = {option:set() for option in active_node.trivia_question["options"]}

    @cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
    async def send_trivia_q(self, active_node, event):
        '''send the message with the trivia question'''
        #TODO: localization
        trivia_q_settings = active_node.trivia_question
        #TODO: fancier looking message?
        message_settings = {
            "content": "Your question is...\n"+trivia_q_settings["question"],
            "components":[{"type":"Button","custom_id":option, "label":option} for option in trivia_q_settings["options"]]
        }
        final_settings = {"menu": True, "message":message_settings}
        if hasattr(active_node, "dest_channel"):
            final_settings.update({"redirect": {"dest_channel_id": active_node.dest_channel.id}})
        await DialogDiscordBaseFuncs.send_message(active_node, event, final_settings)


    @cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
    async def tally_trivia_button_response(self, active_node, event):
        '''counts responses from unique users per option. only one selection per user allowed'''
        chosen_option = event.data["custom_id"]
        user = event.user
        for option, respondants in active_node.tally.items():
            if option == chosen_option:
                respondants.add(user.id)
            else:
                if user.id in respondants:
                    respondants.remove(user.id)
        await event.response.send_message(ephemeral=True, content=f"you have chosen: {chosen_option}")

    @cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.TRANSITION_FILTER])
    def trivia_is_answered(self, active_node, event, goal_node):
        '''checks if trivia should be closed now or not'''
        if hasattr(active_node, "max_correct_answers"):
            return sum([len(responses) for option, responses in active_node.tally.items() if option in active_node.trivia_question["answers"]]) >= active_node.max_correct_answers
        return False

    @cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
    async def close_trivia_q(self, active_node, event):
        '''does the closing actions by clearing possible buttons and '''
        trivia_q_settings = active_node.trivia_question
        message_settings = {
            "content": "**Question closed!**\n"+trivia_q_settings["question"]+"\n Responses: \n" + " | ".join([option + ": " + str(len(responses)) for option,responses in active_node.tally.items()]) + "\n The correct answers were: " + ",".join(trivia_q_settings["answers"])
        }
        await DialogDiscordBaseFuncs.edit_message(active_node, event, {"message":message_settings})

async def setup(bot):
    await bot.add_cog(Trivia(bot))
