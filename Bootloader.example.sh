#!/bin/bash
cd /home/username/botfolder/venv
source bin/activate
cd /home/username/botfolder
pip install --upgrade pip
pip install --upgrade pip-tools
pip-sync
python3.9 bot.py