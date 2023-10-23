import math

import discord
from discord import ui

import discord.ext.commands as MessageCommands

import Examples.Discord.DiscordUtils as DiscordUtils
import src.utils.callbackUtils as cbUtils
from src.utils.Enums import POSSIBLE_PURPOSES

def setup_paging(active_node, source_dict_ref, to_display, page_size = 20):
    '''utility to set up given node as one that shows a long list of items in sections. since discord can only show so much info in one message we
    will need sections'''
    #TODO: potentially would work better as node type?
    active_node.source_list = source_dict_ref
    active_node.pages = [list(to_display.keys())[x*page_size:(x+1)*page_size] for x in range(0, math.ceil(len(to_display)/page_size))]
    active_node.display_page = 0

# VERY ROUGH proof of concept of using a handler to respond to requests on status and analyze other handler
@cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION], has_parameter="optional")
async def save_cog(active_node, event, save_location="node"):
    '''saves which cog the command (focused on message based ones) is executed from into node and/or session data under the key `query_cog`'''
    if type(save_location) is str:
        save_location = [save_location]

    if isinstance(event, MessageCommands.Context):
        cog = event.cog
        if cog is None:
            to_save = None
        else:
            to_save = cog.qualified_name

        if "node" in save_location:
            active_node.query_cog = to_save
        if "session" in save_location:
            active_node.session.data["query_cog"] = to_save

@cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
async def show_server_config(active_node, event):
    '''WIP shows the overview of the server's configuration options'''
    bot = active_node.handler.bot
    embed_settings = {"fields":[]}
    # for cog


@cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
async def change_page(active_node, event):
    '''for nodes that are set up for paging, respond to buttons to change the displayed page. These buttons should have ids that 
    are `next_page`, and `prev_page`'''
    if event.data["custom_id"] == "next_page":
        active_node.display_page += 1
    elif event.data["custom_id"] == "prev_page":
        active_node.display_page -= 1
    
    if active_node.display_page < 0:
        active_node.display_page = len(active_node.pages) - 1
    elif active_node.display_page == len(active_node.pages):
        active_node.display_page = 0

@cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
async def send_all_menus_overview(active_node, event):
    '''WIP shows overview of status for all bot's menu handlers'''
    bot = active_node.handler.bot
    # NOTE: paging for this not implemnted yet
    active_node.loaded_menus_page = 0
    active_node.menus_pages_split = []
    page = []
    for menu in bot.menu_handlers.keys():
        page.append(menu)
        if len(page) == 25:
            active_node.menus_pages_split.append(page)
            page = []
    if len(page) > 0:
        active_node.menus_pages_split.append(page)
        
    embed_settings = {"fields":[]}
    for name in active_node.menus_pages_split[active_node.loaded_menus_page]:
        handler = bot.menu_handlers[name]
        value = "graph nodes: " + str(len(handler.graph_nodes)) + "\n" +\
        "active?: "+ str(len(handler.active_nodes)) + "\n" +\
        "cleans: " + handler.cleaning_status["state"].name + "\n" +\
        "funcs: " + str(len(handler.functions))
        embed_settings["fields"].append({"name":name,"value":value})
    embed = DiscordUtils.build_embed(embed_settings=embed_settings)

    component_options = [{"label": name, "value": name} for name in active_node.menus_pages_split[active_node.loaded_menus_page]]
    component_settings = {"type": "SelectMenu", "custom_id":"menu_select", "placeholder": "see details for menu", "options":component_options}

    view = ui.View(timeout=None)
    view.add_item(DiscordUtils.build_select_menu(component_settings))

    await event.channel.send(embed=embed, view=view)

@cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.TRANSITION_ACTION])
async def link_menu_display(active_node, event, goal_node):
    '''WIP for the overview of all status handlers, there's a selection for which handler to get more details on. this handlers that event and 
    transitioning to node meant to display the more detailed info'''
    if event.data["component_type"] != discord.ComponentType.select.value:
        return 
    goal_node.menu_handler = event.data["values"][0]

@cbUtils.callback_settings(allowed=[POSSIBLE_PURPOSES.ACTION])
async def send_menu_handler_deets(active_node, event):
    '''WIP for grabbing and showing details for a specific handler'''
    bot = active_node.handler.bot
    handler = bot.menu_handlers[active_node.menu_handler]
    embed_settings = {"fields":[]}
    embed_settings["fields"].append({"name":"graph nodes","value":handler.graph_nodes.keys()})
    embed_settings["fields"].append({"name":"registered functions","value":handler.functions.keys()})
    embed_settings["fields"].append({"name":"more details","value":"there's more, just not enough time to implement the grabbing"})
    embed = DiscordUtils.build_embed(embed_settings=embed_settings)
    await event.channel.send(embed=embed)

dialog_func_info = {change_page:{}, save_cog:{}, show_server_config:{}, send_all_menus_overview:{}, link_menu_display:{}, send_menu_handler_deets:{}}