import os
import traceback
import datetime
import random
import discord
from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_NAME = os.getenv("SERVER_NAME")
DEBUG_CHAN_ID = os.getenv("DEBUG_CHAN_ID")

bot = commands.Bot(command_prefix='!')

@bot.event
async def on_ready():
    guild = discord.utils.get(bot.guilds, name=SERVER_NAME)
    print(f"{bot.user} is connected to the following guild:\n"
        f"{guild.name}(id: {guild.id})")

    members = "\n - ".join([member.name for member in guild.members])
    print(f"Server Members:\n - {members}")
    
@bot.event
async def on_error(event, *args, **kwargs):
    embed = discord.Embed(title=':x: Event Error', colour=0xe74c3c) #Red
    embed.add_field(name='Event', value=event)
    embed.description = '```py\n%s\n```' % traceback.format_exc()
    embed.timestamp = datetime.datetime.utcnow()
    debug_chan = bot.get_channel(int(DEBUG_CHAN_ID))
    if(debug_chan != None):
        await debug_chan.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    embed = discord.Embed(title=':x: Command Error', colour=0xe74c3c) #Red
    embed.add_field(name='Error', value=error)
    embed.add_field(name='Arguments', value=ctx.args)
    embed.add_field(name='Command', value=ctx.command)
    embed.add_field(name='Message', value=ctx.message)
    embed.description = '```py\n%s\n```' % traceback.format_exc()
    embed.timestamp = datetime.datetime.utcnow()
    debug_chan = bot.get_channel(int(DEBUG_CHAN_ID))
    if(debug_chan != None):
        await debug_chan.send(embed=embed)


@bot.command(name="99", help="Responds with a random quote from Brooklyn 99")
async def nine_nine(ctx):
    brooklyn_99_quotes = [
        "I\'m the human form of the 💯 emoji.",
        "Bingpot!",
        (
            "Cool. Cool cool cool cool cool cool cool, "
            "no doubt no doubt no doubt no doubt."
        ),
    ]

    response = random.choice(brooklyn_99_quotes)
    await ctx.send(response)

@bot.command(name="roll_dice", help="Simulates rolling dice.")
async def roll(ctx, number_of_dice: int, number_of_sides: int):
    dice = [
        str(random.choice(range(1, number_of_sides + 1)))
        for _ in range(number_of_dice)
    ]
    await ctx.send(', '.join(dice))

bot.run(TOKEN)
