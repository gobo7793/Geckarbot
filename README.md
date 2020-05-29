# Geckarbot
A simple discord bot for the #storm server

### Requirements from server administration
- No execution of mod and admin functions
- Don't interfere basic server features and functions
- GDPR and server etiquette compliance
- Blacklist for users who abused the bot (Mod-only management)

### Current Features
Management:
- Blacklisting users (mod-only)

Sport:
- Get kicker.de Bundesliga table links

Fun/Misc:
- Roll a dice
- Get and set info for current DSC (Host, State, YT link, state end date)

See full command list with `!help`

### For devs:
The bot requires a `.env` file in base directory with the environment data:
```
DISCORD_TOKEN= # Discord bot token to connect
SERVER_NAME= # The name of the connected server
DEBUG_CHAN_ID= # Channel ID for channel for debug output
DEBUG_MODE= # If true, most debug output (like full exception stack) will print on console
```
Required pip packages:
- discord.py 
- dateutils
- python-dotenv
