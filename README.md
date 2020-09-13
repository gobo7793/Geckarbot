# Geckarbot
A simple discord bot for the Communityserver

### Requirements from server administration
- Blacklist and unsubscribing from bot games participation
- No (execution of) special rights which aren't wanted by administration or users
- Administration stuff must be logged directly on admin channel
- Administration stuff only executable by administration

### Current Features
Some of the current Geckarbot features includes:
- Plugin API and Config API to add and manage feature plugins and its configuration
- Subsystems for common used features like reaction and timer listeners
- Ignore list to block users, commands or commands for specific users
- Role management including self-assignable roles via reactions
- Some useful or just funny commands, including custom cmds which can be added and managed by users
- Manage data for server events
- Some games like a kwiss or number guessing

See full command list with `!help` or in [the wiki](https://github.com/gobo7793/Geckarbot/wiki/Commands).

### For devs:
The bot requires a json file for its system configuration stored as `config/geckarbot.json`. See [the wiki](https://github.com/gobo7793/Geckarbot/wiki/Plugin-and-Config-API#bot-system-configuration) for full information about.

Required pip packages:
- discord.py 
- dateutils
- emoji
- espn_api (for fantasy plugin)
- google-api-python-client (if sheetsclient will be used)
- google-auth-httplib2 (if sheetsclient will be used)

All pip packages can be installed using `pip3 install -r requirements.txt`.

To start the bot, you need an own Discord server and Discord application with a bot user. Discord applications can created at [Discord's Developer Portal](https://discord.com/developers/applications):
1. Create Application
2. Create a Bot for the app
3. Get the Bot token and put it into `DISCORD_TOKEN` in `config/geckarbot.json` file
4. Get the OAuth2-URL for the Bot
5. Open the URL and add the Bot to a Server (you need Manage Server permissions for this)

To start the bot:
- Easy and full start: `./runscript.sh`
- For devs: `python3 Geckarbot.py`
