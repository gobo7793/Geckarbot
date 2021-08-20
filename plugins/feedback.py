import logging
from datetime import datetime

import discord.utils
from discord.ext import commands

from base import BasePlugin
from data import Storage, Config, Lang
from botutils import converters
from botutils.utils import add_reaction, helpstring_helper
from botutils.stringutils import paginate, format_andlist


class Complaint:
    """
    Represents a complaint.
    """
    def __init__(self, plugin, complaint_id, author, msg_link, content, category, timestamp):
        """
        :param plugin: Plugin object
        :param complaint_id: unique complaint id
        :param author: Complaint author; User object
        :param msg_link: URL to message
        :param content: Complaint message content
        :param category: Category, can be None
        :param timestamp: datetime.datetime timestamp
        """
        self.plugin = plugin
        self.id = complaint_id
        self.author = author
        self.msg_link = msg_link
        self.content = content
        self.category = category
        self.timestamp = timestamp

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
            "category": self.category,
            "timestamp": self.timestamp,
        }

    @classmethod
    def deserialize(cls, plugin, cid, d):
        """
        Constructs a Complaint object from a dict.

        :param plugin: Plugin reference
        :param cid: Complaint id
        :param d: dict made by serialize()
        :return: Complaint object
        """
        author = discord.utils.get(plugin.bot.guild.members, id=d["authorid"])
        return cls(plugin, cid, author, d["msglink"], d["content"], d["category"], d["timestamp"])

    @classmethod
    def from_message(cls, plugin, msg):
        """
        Parses a `!complain` command message.

        :param plugin: Plugin reference
        :param msg: Message that is to be parsed
        :return: resulting Complaint object
        """
        content = msg.content[len("!complain"):].strip()  # todo check if necessary
        if not content.strip():
            return None
        return cls(plugin, plugin.get_new_id(), msg.author, msg.jump_url, content, None, datetime.now())

    def to_message(self, show_cat=True, show_ts=True, include_url=True):
        """
        Converts the complaint to a human readable message.

        :param show_cat: Flag that determines whether the category is to be shown.
        :param show_ts: Flag that determines whether the timestamp is to be shown.
        :param include_url: Flag that determines whether the message jump URL is to be shown.
        :return: Message string
        """
        authorname = "Not found"
        if self.author is not None:
            authorname = converters.get_best_username(self.author)
        r = "**#{}**: {}: {}".format(self.id, authorname, self.content)
        if self.timestamp is not None and show_ts:
            r += "\n{}".format(self.timestamp.strftime("%d.%m.%Y %H:%M"))
        if include_url and self.msg_link is not None:
            r += "\n{}".format(self.msg_link)
        if show_cat and self.category is not None:
            r += "\n{}".format(Lang.lang(self.plugin, "redact_cat_appendix", self.category))
        return r


def to_msg(el: Complaint):
    return el.to_message()


class Plugin(BasePlugin, name="Feedback"):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, category_desc=Lang.lang(self, "cat_desc"))

        self.logger = logging.getLogger(__name__)
        self.storage = Storage.get(self)
        self.bugscore = Storage.get(self, container="bugscore")["bugscore"]
        self.migrate()
        self.complaints = {}
        self.highest_id = None
        self.complaints_version = self.storage["version"]

        for cid in self.storage["complaints"]:
            cid_i = int(cid)
            self.complaints[cid_i] = Complaint.deserialize(self, cid_i, self.storage["complaints"][cid])

        self.reset_highest_id()

    def default_storage(self, container=None):
        if container is None:
            return {
                "complaints": {},
                "version": 1,
            }
        if container == "bugscore":
            return {
                "bugscore": {},
                "version": 1,
            }
        raise RuntimeError("unknown container {}".format(container))

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def migrate(self):
        """
        Storage format version migrations
        """
        # 0 -> 1
        if "version" not in self.storage:
            self.storage["version"] = 1
            Storage.save(self)

        # 1 -> 2
        if self.storage["version"] == 1:
            self.storage["version"] = 2
            for k in self.storage["complaints"]:
                c = self.storage["complaints"][k]
                c["timestamp"] = None
            Storage.save(self)

    def reset_highest_id(self):
        """
        Resets the current highest ID to current highest ID + 1. Used on complaint deletion.
        """
        self.highest_id = 0
        for el in self.complaints:
            assert el > 0
            if el > self.highest_id:
                self.highest_id = el

    def get_new_id(self, increment=True) -> int:
        """
        Acquires a new complaint id

        :param increment: flags that determines whether the current highest ID is to be incremented (used if the result
            of this function is to be used)
        :return: free unique id that can be used for a new complaint
        """
        if increment:
            self.highest_id += 1
        return self.highest_id

    def write(self):
        """
        Saves the complaints to storage.
        """
        r = {}
        for complaint in self.complaints.values():
            r[complaint.id] = complaint.serialize()
        Storage.get(self)["complaints"] = r
        Storage.save(self)

    def parse_args(self, args, ignore=None):
        """
        Parses the args passed to `!redact`.

        :param args: list of arguments
        :param ignore: List of arguments to ignore
        :return: `ids, cats` with ids the complaint IDs cats the category names that were passed.
        """
        ignore = ignore if ignore else []
        ids = []
        cats = []
        for arg in args:
            if arg in ignore:
                continue
            if arg in ["last", "latest", "-1"]:
                ids.append(self.get_new_id(increment=False))
                continue

            isint = False
            try:
                ids.append(int(arg))
                isint = True
            except (ValueError, TypeError):
                pass

            if not isint:
                cats.append(arg.lower())

        return ids, cats

    @commands.group(name="redact",
                    invoke_without_command=True)
    @commands.has_any_role(*Config().ADMIN_ROLES)
    async def cmd_redact(self, ctx, *args):
        aliases = ["all", "full"]
        full = len(args) > 0 and args[0] in aliases

        # Build complaints list and calculate sums
        ids, cats = self.parse_args(args, ignore=aliases)
        partial = not(len(ids) == 0 and len(cats) == 0)
        complaints = {}
        categorized = 0
        uncategorized = 0
        for index, complaint in self.complaints.items():
            partial_match = index in ids or complaint.category in cats
            full_match = not partial and (full or complaint.category is None)
            if partial_match or full_match:
                complaints[index] = complaint

            # Sums
            if complaint.category is None:
                uncategorized += 1
            else:
                categorized += 1
        csum = categorized + uncategorized
        if len(complaints) == 0:
            if partial:
                complaints = self.complaints
            else:
                await ctx.send(Lang.lang(self, "redact_no_complaints"))
                return

        msgs = [complaint.to_message() for complaint in complaints.values()]

        if partial:
            sumstr = Lang.lang(self, "redact_title_partial", csum, len(msgs))
        elif full:
            sumstr = Lang.lang(self, "redact_title_full", csum, categorized, uncategorized)
        else:
            sumstr = Lang.lang(self, "redact_title_uncat", uncategorized, categorized)

        msgs = paginate(msgs,
                        prefix=Lang.lang(self, "redact_title", sumstr),
                        delimiter="\n\n",
                        msg_prefix="_ _\n")
        for el in msgs:
            await ctx.send(el)

    @cmd_redact.command(name="del")
    async def cmd_delete(self, ctx, *args):
        cids, _ = self.parse_args(args)
        cids = set(cids)
        not_found = []
        # Delete
        for cid in cids:
            if cid not in self.complaints:
                not_found.append("**#{}**".format(cid))
        if not_found:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "redact_del_not_found", format_andlist(not_found)))
            return
        for cid in cids:
            try:
                del self.complaints[cid]
            except KeyError:
                await add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send("PANIC")
                return
        self.write()
        self.reset_highest_id()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_redact.command(name="search")
    async def cmd_search(self, ctx, *args):
        if len(args) == 0:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "redact_search_args"))
            return

        r = []
        for complaint in self.complaints.values():
            found = True
            for searchterm in args:
                # Search check
                if searchterm.lower() not in complaint.to_message(show_cat=False, include_url=False).lower():
                    found = False
                    break
            if not found:
                continue

            # Search result
            r.append(complaint)

        if not r:
            await ctx.send(Lang.lang(self, "redact_search_not_found"))
            return

        msgs = paginate(r, prefix=Lang.lang(self, "redact_search_title"), delimiter="\n\n", f=to_msg)
        for el in msgs:
            await ctx.send(el)

    @cmd_redact.command(name="count")
    async def cmd_count(self, ctx):
        cats = set()
        uncategorized = 0
        categorized = 0
        for complaint in self.complaints.values():
            if complaint.category is not None:
                cats.add(complaint.category)
                categorized += 1
            else:
                uncategorized += 1
        total = uncategorized + categorized
        await ctx.send(Lang.lang(self, "redact_count", total, categorized, uncategorized, len(cats)))

    @cmd_redact.command(name="flatten", hidden=True)
    async def cmd_flatten(self, ctx):
        i = 0
        new = {}
        for el in sorted(self.complaints.keys()):
            i += 1
            new[i] = self.complaints[el]
            new[i].id = i

        self.complaints = new
        self.highest_id = i
        self.write()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def category_move(self, ctx, complaint_ids: list, category):
        """
        Moves complaints to a category.

        :param ctx: Context
        :param complaint_ids: List of IDs of (existing!) complaints to be moved
        :param category: New category; category will be removed from complaints if this is None
        """
        assert complaint_ids
        msgs = []
        for cid in complaint_ids:
            precat = self.complaints[cid].category
            self.complaints[cid].category = category

            # Category removed from complaint with existing category
            if category is None and precat is not None:
                msgs.append(Lang.lang(self, "redact_cat_removed", cid, precat))

            # Existing category changed
            elif precat is not None and category is not None:
                msgs.append(Lang.lang(self, "redact_cat_moved", cid, precat, category))

        self.write()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        if msgs:
            for msg in paginate(msgs):
                await ctx.send(msg)

    async def category_show(self, ctx, category):
        """
        Shows the content of a category.

        :param ctx: Context
        :param category: Category that is to be shown
        """
        msgs = []
        for complaint in self.complaints.values():
            if complaint.category == category:
                msgs.append(complaint.to_message(show_cat=False))

        if not msgs:
            await ctx.send(Lang.lang(self, "redact_cat_not_found", category))
            return

        for msg in paginate(msgs,
                            prefix=Lang.lang(self, "redact_cat_show_prefix", category, len(msgs)),
                            delimiter="\n\n",
                            msg_prefix="_ _\n"):
            await ctx.send(msg)

    async def category_list(self, ctx):
        """
        Lists all categories.

        :param ctx: Context
        """
        cats = {}
        cats_sorted = []
        for cat in self.complaints.values():
            cat = cat.category
            if cat is not None:
                if cat in cats:
                    cats[cat] += 1
                else:
                    cats_sorted.append(cat)
                    cats[cat] = 1
        cats_sorted = sorted(cats_sorted, key=lambda x: x.lower())
        for i in range(len(cats_sorted)):
            cats_sorted[i] = "{} ({})".format(cats_sorted[i], cats[cats_sorted[i]])

        if not cats:
            await ctx.send(Lang.lang(self, "redact_cat_list_empty"))
        else:
            for msg in paginate(cats_sorted, prefix=Lang.lang(self, "redact_cat_list_prefix")):
                await ctx.send(msg)

    @cmd_redact.command(name="category", aliases=["cat", "cats", "categories"])
    async def cmd_category(self, ctx, *args):
        ids, cats = self.parse_args(args)

        # Errors / arg validation
        error = None
        if len(cats) > 1:
            error = Lang.lang(self, "too_many_args")
        else:
            for cid in ids:
                if cid not in self.complaints:
                    error = Lang.lang(self, "redact_cat_complaint_not_found", cid)
                    break
        if error is not None:
            await ctx.send(error)
            return

        # Determine what to do
        if len(ids) == 0:
            # List
            if len(cats) == 0:
                await self.category_list(ctx)
                return
            await self.category_show(ctx, cats[0])
            return

        # Move
        cat = None
        if len(cats) > 0:
            cat = cats[0]
        await self.category_move(ctx, ids, cat)

    @commands.command(name="complain")
    async def cmd_complain(self, ctx, *args):
        msg = ctx.message
        complaint = Complaint.from_message(self, msg)
        if complaint is None:
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)
            return
        self.complaints[complaint.id] = complaint
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        self.write()

    #####
    # Bugscore
    #####
    async def bugscore_show(self, ctx):
        """
        Sends the current bugscore to ctx.

        :param ctx: Context
        """
        users = sorted(
            sorted(
                [(converters.get_best_username(discord.utils.get(self.bot.guild.members, id=user)), n) for (user, n) in
                 self.bugscore.items()],
                key=lambda x: x[0].lower()),
            key=lambda x: x[1],
            reverse=True
        )

        # Handle empty bug score
        if len(users) == 0:
            await ctx.send(Lang.lang(self, "bugscore_empty"))
            return

        # Format populated bug score
        lines = []
        for i in range(len(users)):
            user, p = users[i]
            lines.append("**#{}** {}: {}".format(i + 1, user, p))
        for msg in paginate(lines, prefix="{}\n".format(Lang.lang(self, "bugscore_title"))):
            await ctx.send(msg)

    async def bugscore_del(self, ctx, user):
        """
        Removes a user from the bugscore.

        :param ctx: Context
        :param user: User to remove
        """
        if discord.utils.get(ctx.author.roles, id=Config().BOT_ADMIN_ROLE_ID) is None:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            return
        try:
            user = await commands.MemberConverter().convert(ctx, user)
        except (commands.CommandError, IndexError):
            await ctx.send(Lang.lang(self, "bugscore_user_not_found", user))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        if user.id in self.bugscore:
            del self.bugscore[user.id]
            Storage.save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)

    @commands.has_any_role(Config().BOT_ADMIN_ROLE_ID)
    async def bugscore_increment(self, ctx, user, increment):
        """
        Incrementation branch of bugscore cmd

        :param ctx: Context
        :param user: User whose bugscore is to be incremented
        :param increment: Value to increment by
        """
        if discord.utils.get(ctx.author.roles, id=Config().BOT_ADMIN_ROLE_ID) is None:
            await add_reaction(ctx.message, Lang.CMDNOPERMISSIONS)
            return

        # find user
        try:
            user = await commands.MemberConverter().convert(ctx, user)
        except (commands.CommandError, IndexError):
            await ctx.send(Lang.lang(self, "bugscore_user_not_found", user))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        try:
            increment = int(increment)
        except (ValueError, TypeError):
            await ctx.send(Lang.lang(self, "bugscore_nan", increment))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        if user.id in self.bugscore:
            self.bugscore[user.id] += increment
        else:
            self.bugscore[user.id] = increment
        if self.bugscore[user.id] <= 0:
            del self.bugscore[user.id]
        Storage.save(self, container="bugscore")
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @commands.command(name="bugscore")
    async def cmd_bugscore(self, ctx, *args):
        if len(args) == 0:
            await self.bugscore_show(ctx)
            return

        if len(args) == 2 and args[0] == "del":
            await self.bugscore_del(ctx, args[1])
            return

        increment = 1
        if len(args) == 2:
            increment = args[1]

        if len(args) > 2:
            await ctx.send(Lang.lang(self, "bugscore_args"))
            return

        await self.bugscore_increment(ctx, args[0], increment)
