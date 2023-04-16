# Server-Side Bot Maintenance

This guide details regular tasks that may need to be performed to keep the bot running smoothly. The folder names, service name, etc. are dependent on your own setup, so if you've chosen different names for them, substitute those when using this guide.

## Starting, Stopping, Restarting

Commands to start, stop, restart and check status:
```bash
sudo systemctl stop opelibot
sudo systemctl start opelibot
sudo systemctl restart opelibot
sudo systemctl status opelibot
```

## Bot logging

Logs for startup are detailed and will be helpful in identifying conditions that could lead to instability or inability of the bot to function.

Bot logs are stored in the bot directory in a folder called "logs." Watch the log in realtime like this:

```bash
tail -F ~/opelibot/logs/opelibot.log
```

The syslog may also have additional useful information:

```bash
sudo tail -F /var/log/syslog
```

Logs for other services that are related but not dependencies of the bot:

```bash
/var/log/grafana/grafana.log
/var/log/influxd.log
/var/log/prometheus
/var/log/mysql/error.log
# The logs below are disabled by default. See your mysql configs to enable them if you need to troubleshoot mysql
/var/log/mysql/mysql.log
/var/log/mysql/mysql-slow.log
```

# Other documentation:
* [README](../README.md)
* [Deploying the Bot](deploy.md)
* [Guild Setup](guild_setup.md)

