import discord

from Geckarbot import BasePlugin
from botutils import utils


class ReactionEventData():
    """
    Tuple for easier reaction event handling.
    """

    def __init__(self, user, channel, message, emoji, member = None):
        self.user = user
        self.channel = channel
        self.message = message
        self.emoji = emoji

        self.member = member

    async def convert(bot, payload: discord.RawReactionActionEvent):
        """
        Converts the raw payload data from on_raw_reaction_add and on_raw_reaction_remove
        to usable instances for easier event handling.
        :param bot: the bot instance to use to convert
        :param payload: the payload with raw event data
        :return: the converted ReactionEvent instance
        """
        channel = bot.get_channel(payload.channel_id)
        user = bot.get_user(payload.user_id)
        member = None
        try:
            member = self.bot.guild.get_member(payload.user_id)
        except:
            pass
        message = await channel.fetch_message(payload.message_id)

        return ReactionEventData(user, channel, message, payload.emoji, member)


class Plugin(BasePlugin, name="Role Management"):

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)
        
        @bot.listen()
        async def on_raw_reaction_add(payload):
            pass

        @bot.listen()
        async def on_raw_reaction_remove(payload):
            pass


        #@bot.listen()
        #async def on_raw_reaction_add(payload):
        #    channel = self.bot.get_channel(payload.channel_id)
        #    user = self.bot.guild.get_member(payload.user_id)
        #    message = await channel.fetch_message(payload.message_id)
        #    emoji = payload.emoji

        #    msg = f"{channel.name}, {utils.get_best_username(user)}, {emoji} added\n{message.content}"

        #    await utils.write_debug_channel(self.bot, msg)

        #    new_emoji = discord.utils.get(bot.emojis, name='mud')
        #    await message.add_reaction(new_emoji)

        #@bot.listen()
        #async def on_raw_reaction_remove(payload):
        #    channel = self.bot.get_channel(payload.channel_id)
        #    user = self.bot.guild.get_member(payload.user_id)
        #    message = await channel.fetch_message(payload.message_id)
        #    emoji = payload.emoji

        #    msg = f"{channel.name}, {utils.get_best_username(user)}, {emoji} removed\n{message.content}"

        #    await utils.write_debug_channel(self.bot, msg)
            
        #    new_emoji = discord.utils.get(bot.emojis, name='kip')
        #    await message.add_reaction(new_emoji)

    async def add_user_role(payload):
        pass

    async def remove_user_role(payload):
        pass

    async def add_server_role(payload):
        pass

    async def remove_server_role(payload):
        pass
