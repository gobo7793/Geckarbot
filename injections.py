import discord.ext.commands.view
import discord.ext.commands.help


def pre_injections():
    quotes = discord.ext.commands.view._quotes
    quotes["‚"] = "’"
    quotes["„"] = "“"
    discord.ext.commands.view._all_quotes = set(quotes.keys()) | set(quotes.values())


def post_injections(bot):
    # discord.ext.commands.help.DefaultHelpCommand.command_not_found = bot.helpsys.command_not_found
    pass
