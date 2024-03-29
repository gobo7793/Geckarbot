import nextcord.ext.commands.view
import nextcord.ext.commands.help


# pylint: disable=protected-access,unused-argument

def pre_injections():
    """Some injections for workarounds for some bugs/problems BEFORE creation of bot object"""
    quotes = nextcord.ext.commands.view._quotes
    quotes["‚"] = "’"
    quotes["„"] = "“"
    nextcord.ext.commands.view._all_quotes = set(quotes.keys()) | set(quotes.values())


def post_injections(bot):
    """Some injections for workarounds for some bugs/problems AFTER creation of bot object"""
    # as far as nothing is here
    # discord.ext.commands.help.DefaultHelpCommand.command_not_found = bot.helpsys.command_not_found
