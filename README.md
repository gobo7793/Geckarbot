# Geckarbot
A simple discord bot for the #storm server

### Requirements from server administration
- No execution of mod and admin functions
- Don't interfere basic server features and functions
- GDPR and server etiquette compliance
- Blacklist for users who abused the bot (Mod-only management)

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
SERVER_ID= # The name of the connected server
DEBUG_CHAN_ID= # Channel ID for channel for debug output
DSC_CHAN_ID= # Channel ID for !dsc command
DEBUG_MODE= # Not neccessary, but if true, most debug output (like full exception stack) will print on console
```
Required pip packages:
- discord.py 
- dateutils
- python-dotenv

To start the bot: `python3 Geckarbot.py`

Notes: To start the bot, you need an own Discord server and Discord application. Discord applications can created at [Discords Developer Portal](https://discord.com/developers/applications).
