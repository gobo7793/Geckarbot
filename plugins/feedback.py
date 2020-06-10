from discord.ext import commands

from Geckarbot import BasePlugin
from conf import Config


lang = {
    "complaint_received": "Please hold the line! A human will contact you soon.",
}


skeleton_config = {
    "complaints": []
}


class Complaint:
    def __init__(self, complaint_id, author, message, content):
        """
        :param complaint_id: unique complaint id
        :param author:
        :param message:
        :param content:
        """
        self.id = complaint_id
        self.author = author
        self.message = message
        self.content = content

    def serialize(self):
        """
        :return: A dict with the keys id, authorid, messageid, channel, content
        """
        r = {
            "id": self.id,
            "authorid": self.message.author.id,

        }

    @classmethod
    def deserialize(cls, d):
        """
        Constructs a Complaint object from a dict.
        :param d: dict made by serialize()
        :return: Complaint object
        """
        pass

    @classmethod
    def from_message(cls, msg):
        pass


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        self.storage = Config().get(self)
        self.complaints = {}
        self.highest_id = None

        self.get_new_id(init=True)

        for el in self.storage["complaints"]:
            complaint = Complaint.deserialize(el)
            self.complaints[complaint.id] = complaint

        bot.register(self)

    def get_new_id(self, init=False):
        """
        Acquires a new complaint id
        :param init: if True, only sets self.highest_id but does not return anything. Useful for plugin init.
        :return: free unique id that can be used for a new complaint
        """
        if self.highest_id is None:
            self.highest_id = 0
            for el in self.complaints:
                if el > self.highest_id:
                    self.highest_id = el
        if not init:
            self.highest_id += 1
            return self.highest_id

    @commands.command(name="complain", help="Takes a complaint and stores it")
    def complain(self, ctx, *args):
        msg = ctx.message
        content = msg.content[len("!complain"):].strip()
        complaint = Complaint(self.get_new_id(), ctx.message.author, msg, content)
        self.complaints[complaint.id] = complaint
