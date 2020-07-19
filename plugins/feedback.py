from copy import deepcopy

import discord.utils
from discord.ext import commands

from Geckarbot import BasePlugin
from conf import Config
from botutils import utils, permChecks


lang = {
    "complaint_received": "Complaint received. Please hold the line! A human will contact you soon. Maybe.",
    "complaint_removed": "Complaint #{} removed.",
}


def str_keys_to_int(d):
    """
    Converts {"22": "foo", "44": "bar"} to {22: "foo", 44: "bar"}
    """
    todel = []
    toadd = {}
    for el in d:
        toadd[int(el)] = d[el]
        todel.append(el)
    for el in todel:
        del d[el]
    for el in toadd:
        d[el] = toadd[el]


class Complaint:
    def __init__(self, complaint_id, author, msg_link, content):
        """
        :param complaint_id: unique complaint id
        :param author:
        :param msg_link:
        :param content:
        """
        self.id = complaint_id
        self.author = author
        self.msg_link = msg_link
        self.content = content

    def serialize(self):
        """
        :return: A dict with the keys id, authorid, messageid, channel, content
        """
        authorid = None
        if self.author is not None:
            authorid = self.author.id

        return {
            "id": self.id,
            "authorid": authorid,
            "msglink": self.msg_link,
            "content": self.content,
        }

    @classmethod
    def deserialize(cls, bot, cid, d):
        """
        Constructs a Complaint object from a dict.
        :param bot: Geckarbot reference
        :param cid: Complaint id
        :param d: dict made by serialize()
        :return: Complaint object
        """
        author = discord.utils.get(bot.guild.members, id=d["authorid"])
        return Complaint(cid, author, d["msglink"], d["content"])

    @classmethod
    def from_message(cls, plugin, msg):
        content = msg.content[len("!complain"):].strip()  # todo check if necessary
        return cls(plugin.get_new_id(), msg.author, msg.jump_url, content)

    def to_message(self):
        authorname = "Not found"
        if self.author is not None:
            authorname = utils.get_best_username(self.author)
        r = "**#{}**: {}: {}".format(self.id, authorname, self.content)
        if self.msg_link is not None:
            r += "\n{}".format(self.msg_link)
        return r


def complaint_message_list(complaints):
    threshold = 1900
    starter = "**Complaints:**\n"
    current_msg = []
    msgs = []
    delimiter = "\n\n"
    first = True
    for i in complaints:
        el = complaints[i]

        to_add = el.to_message()
        if len(to_add) > threshold:  # really really long complaints
            msgs.append([to_add])
            continue

        if first:
            first = False
            to_add = starter + to_add

        # sum up current len
        length = 0
        for k in current_msg:
            length += len(k) + len(delimiter)

        if length + len(to_add) > threshold:
            msgs.append(current_msg)
            current_msg = ["_ _\n" + to_add]
        else:
            current_msg.append(to_add)
    msgs.append(current_msg)

    r = []
    for el in msgs:
        r.append(delimiter.join(el))
    return r


class Plugin(BasePlugin, name="Feedback"):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)

        self.storage = Config.get(self)
        self.complaints = {}
        self.highest_id = None

        # Load complaints from storage
        if self.storage is None:
            self.storage = deepcopy(self.default_config())
        else:
            str_keys_to_int(self.storage["complaints"])
        for cid in self.storage["complaints"]:
            self.complaints[cid] = Complaint.deserialize(self.bot, cid, self.storage["complaints"][cid])

        self.get_new_id(init=True)

    def default_config(self):
        return {
            "complaints": {}
        }

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

    def write(self):
        r = deepcopy(self.default_config())
        for el in self.complaints:
            complaint = self.complaints[el]
            r["complaints"][complaint.id] = complaint.serialize()
        Config.set(self, r)
        Config.save(self)

    @commands.group(name="redact", invoke_without_command=True,
                    help="Redacts the list of complaints (i.e. read and delete)", usage="[del x]",
                    description="Returns the accumulated feedback. Use [del x] to delete feedback #x.")
    @commands.has_any_role(Config().ADMIN_ROLE_ID, Config().BOTMASTER_ROLE_ID)
    async def redact(self, ctx):
        # Printing complaints
        if len(self.complaints) == 0:
            await ctx.send(Config.lang(self, "redact_no_complaints"))
            return

        msgs = complaint_message_list(self.complaints)
        for el in msgs:
            await ctx.send(el)

    @redact.command(name="del", help="Deletes a complaint", usage="<#>")
    async def delete(self, ctx, *args):
        # Args parsing
        argserr = False
        if len(args) != 1:
            argserr = True
        i = None
        try:
            i = int(args[0])
        except (ValueError, TypeError):
            argserr = True
        if argserr:
            await ctx.message.add_reaction(Config().CMDERROR)
            await ctx.send(Config.lang(self, "redact_del_args"))
            return

        # Delete
        try:
            del self.complaints[i]
        except KeyError:
            await ctx.message.add_reaction(Config().CMDERROR)
            await ctx.send(Config.lang(self, "redact_del_not_found", i))
            return
        # await ctx.send(lang['complaint_removed'].format(i))
        await ctx.message.add_reaction(Config().CMDSUCCESS)
        self.write()

    @redact.command(name="search", help="Finds all complaints that contain all search terms", usage="<search terms>")
    async def search(self, ctx, *args):
        if len(args) == 0:
            await ctx.message.add_reaction(Config().CMDERROR)
            await ctx.send(Config.lang(self, "redact_search_args"))

        r = {}
        for i in self.complaints:
            complaint = self.complaints[i]
            found = True
            for searchterm in args:
                # Search check
                if searchterm.lower() not in complaint.to_message().lower():
                    found = False
                    break
            if not found:
                continue

            # Search result
            r[i] = complaint

        if not r:
            await ctx.send(Config.lang(self, "redact_search_not_found"))
            return
        msgs = complaint_message_list(r)
        for el in msgs:
            await ctx.send(el)

    @commands.command(name="complain", help="Takes a complaint and stores it", usage="<message>",
                      description="Delivers a feedback message. "
                                  "The admins and botmasters can then read the accumulated feedback. "
                                  "The bot saves the feedback author, "
                                  "the message and a link to the message for context.")
    async def complain(self, ctx, *args):
        msg = ctx.message
        complaint = Complaint.from_message(self, msg)
        self.complaints[complaint.id] = complaint
        await ctx.message.add_reaction(Config().CMDSUCCESS)
        # await msg.channel.send(lang["complaint_received"])
        self.write()
