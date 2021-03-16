import discord.ext.commands.view
import discord.ext.commands.help


# pylint: disable=protected-access

def pre_injections():
    """Some injections for workarounds for some bugs/problems BEFORE creation of bot object"""
    quotes = discord.ext.commands.view._quotes
    quotes["‚"] = "’"
    quotes["„"] = "“"
    discord.ext.commands.view._all_quotes = set(quotes.keys()) | set(quotes.values())


def post_injections(bot):
    """Some injections for workarounds for some bugs/problems AFTER creation of bot object"""
    # pylint: disable=unused-argument
    # as far as nothing is here
    # discord.ext.commands.help.DefaultHelpCommand.command_not_found = bot.helpsys.command_not_found
