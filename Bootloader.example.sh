#!/bin/bash
cd /home/username/botfolder/venv
source bin/activate
cd /home/username/botfolder
pip-sync
python3.9 bot.py