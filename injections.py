import discord.ext.commands.view
import discord.ext.commands.help


def pre_injections():
    discord.ext.commands.view._quotes = {}
    discord.ext.commands.view._all_quotes = set()


def post_injections(bot):
    discord.ext.commands.help.DefaultHelpCommand.command_not_found = bot.helpsys.command_not_found
