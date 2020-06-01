# Geckarbot
A simple discord bot for the Communityserver

### Requirements from server administration
- Blacklist and unsubscribing from bot games participation
- No (execution of) special rights which aren't wanted by administration or users
- Administration stuff must be logged directly on admin channel
- Administration stuff only executable by administration

### Current Features
Management:
- Blacklisting users

Getting data or simple messages:
- kicker.de Bundesliga table links

Fun/Misc:
- Roll a dice
- Get and manage info for current/next DSC (Host, State, YT link, state end date)

See full command list with `!help`

### For devs:
The bot requires a `.env` file in base directory with the environment data:
```
DISCORD_TOKEN= # Discord bot token to connect
SERVER_ID= # The ID of the connected server
DEBUG_CHAN_ID= # Channel ID for channel for debug output
DSC_CHAN_ID= # Channel ID for !dsc command
DEBUG_MODE= # Not neccessary, but if True, most debug output (like full exception stack) will print on console
```
Required pip packages:
- discord.py 
- dateutils
- python-dotenv

To start the bot, you need an own Discord server and Discord application with a bot user. Discord applications can created at [Discords Developer Portal](https://discord.com/developers/applications):
1. Create Application
2. Create a Bot for the app
3. Get the Bot token and put it into `DISCORD_TOKEN` in `.env` file
4. Get the OAuth2-URL for the Bot (eg. use scope `Bot` and Permissions `Send Messages`
5. Open the URL and add the Bot to a Server (you need Manage Server rights for this)

To start the bot: `python3 Geckarbot.py`
