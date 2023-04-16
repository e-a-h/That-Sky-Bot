# Bot Deployment

This section details deployment of the bot to your hosting server.

## Clone the bot

```bash
git clone https://github.com/e-a-h/opelibot.git ~/opelibot
```

## Create a sentry.io project and get the "DSN" for the project.

Refer to [sentry.io](https://sentry.io) For more on this step. The DSN is needed for the bot configuration file. 

## Edit configuration files

The bot comes with a config example, but you must create a config file. Values for the config are all sensitive and will not be repeated here. If you are setting up this bot and don't know what the values should be, then you will not be successful. Config can be populated from the example:
```bash
cd ~/opelibot
cp config.example.json config.json
```

## Create a database

In a mysql client (command line or remote GUI client, doesn't matter) create a database for the new bot. The name is not important, but must match in the bot config file. From a mysql command line, the command is:
```sql
CREATE DATABASE opelibot CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

## Create a Python virtual environment

Create an execution environemnt for the bot. (Exit mysql if you still have it open!) Then:
```bash
cd ~/opelibot
python3.9 -m venv ./venv
```

Any time you want to perform python-specific tasks using the bot codebase, the virtual environment needs to be activated:
```bash
source venv/bin/activate
```

## Install pip-tools and sync with requirements

```bash
pip install pip-tools
pip-sync
```

Now with the virtual environment activated, initialize the database. This will be done **only once**, when configuring a new copy of this bot. Make sure the name given at the end of this command matches the name of the database created above:
```bash
cd ~/bot_dir/
python init_db.py opelibot
```

## Create a system service for the bot

Make a service file for the bot starting with the example service file:
```bash
mkdir ~/bin
cp ~/opelibot/bot.example.service ~/bin/opelibot.service
vi ~/bin/opelibot.service
```

Edit the WorkingDirectory, ExecStart and User lines to match your environment. Edit other info as necessary when deviating from this guide. Ensure that the Bootloader.sh script is executable and contents are correct for your environment.

Start with the Bootloader.example.sh and edit contents to match your environment:

```bash
cd ~/opelibot
cp Bootloader.example.sh Bootloader.sh
vi Bootloader.sh
```

Enable the service!
```bash
sudo systemctl enable /home/username/bin/opelibot.service --now
```

## Start and stop the bot

Details for starting and stopping the bot, and viewing logs can be found in [this document](server_side_maintenance.md).

## Webhook

Grafana can be used to trigger a webhook that restarts the bot in case certain failure conditions are detected. Setting rules for these conditions *is up to you* and should be done with care.

Install webhook
```bash
sudo apt install webhook
```

Copy the example webhook into webhook conf. Check if the file exists first so you don't overwrite anything important:
```bash
cat /etc/webhook.conf
```

If it's nonexistent or empty, then copy the example, edit it, and then restart the webhook service:
```bash
sudo cp ~/opelibot/webhook.example.json /etc/webhook.conf
sudo vi /etc/webhook.conf
```

Create a hook script based on the example file. Edit the file and comment out lines that don't start with "logger" so you can test it without starting or stopping the bot. Then save and make the script executable:
```bash
cp rebot.example.sh rebot.sh
vi rebot.sh
chmod u+x rebot.sh
```

Test the webhook! To verify that it's working, you should tail the syslog in a different window. This is where tmux comes in handy. In one pane:

```bash
tail -F /var/log/syslog
```

In another pane, trigger the webhook:
```bash
curl 'http://localhost:9000/hooks/reboot-bot?token=deadbeat'
```

The response to the curl command should be:
```
bot should be rebooting now...
```

And in the pain with syslog open, you should see something like this:
```
Jan 01 00:00:01 hostname root: [HOOK] starting bot reboot sequence
Jan 01 00:00:01 hostname root: [HOOK] bot has been killed
Jan 01 00:00:01 hostname root: [HOOK] bot starting...
```

If everything works as planned, then you can edit the `rebot.sh` script to uncomment the `sudo` lines that actually do the work! Because the hook is dangerous to expose to the public, there's no need to open port 9000 in the firewall. This webhook will only be used by grafana, which will be running on the same server, accessed via loopback interface.

## Discord Guild Setup

Once the bot is started and invited to the production guild, proceed to the [Guild Setup Guide](guild_setup.md).

# Other documentation:
* [README](../README.md)
* [Server-side Maintenance](server_side_maintenance.md)
