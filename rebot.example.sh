#!/bin/sh
logger "[HOOK] starting bot reboot sequence"
sudo systemctl kill bot.service
logger "[HOOK] bot has been killed"
sudo systemctl start bot.service
logger "[HOOK] bot starting..."