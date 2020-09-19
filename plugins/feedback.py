from copy import deepcopy

import discord.utils
from discord.ext import commands

from base import BasePlugin
from conf import Storage, Config, Lang
from botutils import converters
from botutils.stringutils import paginate


h_usage = "[full]"
h_search_usage = "[<search terms>]"
h_del_usage = "#"
h_cat_usage = "[<# ...> | <# ...> <category> | <category>]"
h_cat_desc = "Manages complaint categories. Usage:\n" \
             "  !redact category                    - lists all categories.\n" \
             "  !redact category <category>         - lists all complaints in a category.\n" \
             "  !redact category <# ...> <category> - adds complaints to a category.\n" \
             "  !redact category <# ...>            - removes the categories from complaints.\n."


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
    def __init__(self, plugin, complaint_id, author, msg_link, content, category):
        """
        :param plugin: Plugin object
        :param complaint_id: unique complaint id
        :param author: Complaint author; User object
        :param msg_link: URL to message
        :param content: Complaint message content
        :param category: Category, can be None
        """
        self.plugin = plugin
        self.id = complaint_id
        self.author = author
        self.msg_link = msg_link
        self.content = content
        self.category = category

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
        return cls(plugin, cid, author, d["msglink"], d["content"], d["category"])

    @classmethod
    def from_message(cls, plugin, msg):
        content = msg.content[len("!complain"):].strip()  # todo check if necessary
        return cls(plugin, plugin.get_new_id(), msg.author, msg.jump_url, content, None)

    def to_message(self, show_cat=True, include_url=True):
        authorname = "Not found"
        if self.author is not None:
            authorname = converters.get_best_username(self.author)
        r = "**#{}**: {}: {}".format(self.id, authorname, self.content)
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
        bot.register(self)

        self.storage = Storage.get(self)
        self.complaints = {}
        self.highest_id = None

        # Load complaints from storage
        if self.storage is None:
            self.storage = deepcopy(self.default_storage())
        else:
            str_keys_to_int(self.storage["complaints"])
        for cid in self.storage["complaints"]:
            self.complaints[cid] = Complaint.deserialize(self, cid, self.storage["complaints"][cid])

        # Migration 1.7 -> 1.8
        if "bugscore" not in self.storage:
            self.storage["bugscore"] = {}
            Storage.save(self)

        self.reset_highest_id()

    def default_storage(self):
        return {
            "complaints": {},
            "bugscore": {},
        }

    def reset_highest_id(self):
        self.highest_id = 1
        for el in self.complaints:
            assert el > 0
            if el > self.highest_id:
                self.highest_id = el

    def get_new_id(self):
        """
        Acquires a new complaint id
        :return: free unique id that can be used for a new complaint
        """
        self.highest_id += 1
        return self.highest_id

    def write(self):
        r = {}
        for el in self.complaints:
            complaint = self.complaints[el]
            r[complaint.id] = complaint.serialize()
        Storage.get(self)["complaints"] = r
        Storage.save(self)

    @commands.group(name="redact",
                    invoke_without_command=True,
                    help="Redacts the list of complaints (i.e. read and delete)",
                    usage=h_usage,
                    description="Returns the accumulated feedback. Use [del x] to delete feedback #x"
                                "and [full] to include categorized complaints.")
    @commands.has_any_role(Config().ADMIN_ROLE_ID, Config().BOTMASTER_ROLE_ID)
    async def redact(self, ctx, *args):
        aliases = ["all", "full"]
        full = True if len(args) > 0 and args[0] in aliases else False

        # Build msg list and calculate sums
        categorized = 0
        uncategorized = 0
        msgs = []
        for el in self.complaints:
            complaint = self.complaints[el]
            if full or complaint.category is None:
                msgs.append(complaint.to_message())

            # Sums
            if complaint.category is None:
                uncategorized += 1
            else:
                categorized += 1

        csum = categorized + uncategorized
        if len(msgs) == 0:
            await ctx.send(Lang.lang(self, "redact_no_complaints"))
            return

        if full:
            sumstr = Lang.lang(self, "redact_title_full", csum, categorized, uncategorized)
        else:
            sumstr = Lang.lang(self, "redact_title_uncat", uncategorized, categorized)

        msgs = paginate(msgs,
                        prefix=Lang.lang(self, "redact_title", sumstr),
                        delimiter="\n\n",
                        msg_prefix="_ _\n")
        for el in msgs:
            await ctx.send(el)

    @redact.command(name="del", help="Deletes a complaint", usage=h_del_usage)
    async def cmd_delete(self, ctx, complaint: int):
        # Delete
        try:
            del self.complaints[complaint]
        except KeyError:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "redact_del_not_found", complaint))
            return
        # await ctx.send(lang['complaint_removed'].format(i))
        self.write()
        self.reset_highest_id()
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @redact.command(name="search", help="Finds all complaints that contain all search terms", usage=h_search_usage)
    async def cmd_search(self, ctx, *args):
        if len(args) == 0:
            await ctx.message.add_reaction(Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "redact_search_args"))
            return

        r = []
        for i in self.complaints:
            complaint = self.complaints[i]
            found = True
            for searchterm in args:
                # Search check
                if searchterm.lower() not in complaint.to_message(include_url=False).lower():
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

    @redact.command(name="count", help="Shows the amount of complaints that exist")
    async def cmd_count(self, ctx):
        cats = set()
        uncategorized = 0
        categorized = 0
        for el in self.complaints:
            complaint = self.complaints[el]
            if complaint.category is not None:
                cats.add(complaint.category)
                categorized += 1
            else:
                uncategorized += 1
        total = uncategorized + categorized
        await ctx.send(Lang.lang(self, "redact_count", total, categorized, uncategorized, len(cats)))

    @redact.command(name="flatten", hidden=True, help="Flattens the complaint IDs")
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
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    async def category_move(self, ctx, complaint_ids: list, category):
        """
        Moves a complaint to a category.
        :param ctx: Context
        :param complaint_ids: List of IDs of (existing!) complaints to be moved
        :param category: New category
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
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
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
        for el in self.complaints:
            complaint = self.complaints[el]
            if complaint.category == category:
                msgs.append(complaint.to_message(show_cat=False))

        if not msgs:
            await ctx.send(Lang.lang(self, "redact_cat_not_found", category))
            return

        for msg in paginate(msgs,
                            prefix=Lang.lang(self, "redact_cat_show_prefix", category),
                            delimiter="\n\n",
                            msg_prefix="_ _\n"):
            await ctx.send(msg)

    async def category_list(self, ctx):
        """
        Lists all categories.
        :param ctx: Context
        """
        cats = []
        for el in self.complaints:
            cat = self.complaints[el].category
            if cat is not None and cat not in cats:
                cats.append(cat)
        cats = sorted(cats, key=lambda x: x.lower())

        if not cats:
            await ctx.send(Lang.lang(self, "redact_cat_list_empty"))
        else:
            for msg in paginate(cats, prefix=Lang.lang(self, "redact_cat_list_prefix")):
                await ctx.send(msg)

    @redact.command(name="category",
                    aliases=["cat"],
                    help="Adds complaints to categories and lists categories.",
                    description=h_cat_desc,
                    usage=h_cat_usage)
    async def category(self, ctx, *args):
        # List
        if len(args) == 0:
            await self.category_list(ctx)
            return

        # Show
        try:
            cid = int(args[0])
        except (ValueError, TypeError):
            # Not an int, therefore interpreted as a category name
            if len(args) != 1:
                await ctx.message.add_reaction(Lang.CMDERROR)
                await ctx.send(Lang.lang(self, "too_many_args"))
            else:
                await self.category_show(ctx, args[0])
            return

        # Move (first arg is an int)
        cids = []
        cat = None
        for i in range(len(args)):
            error = None
            cid = None
            try:
                cid = int(args[i])
            except (ValueError, TypeError):
                if cat is None:
                    cat = args[i]
                else:
                    cid = cat
                    error = "redact_cat_invalid_id"

            if error is None and cid is not None and cid not in self.complaints:
                error = "redact_cat_complaint_not_found"

            if error is not None:
                await ctx.message.add_reaction(Lang.CMDERROR)
                await ctx.send(Lang.lang(self, error, cid))
                return
            else:
                if cid is not None:
                    cids.append(cid)

        await self.category_move(ctx, cids, cat)

    @commands.command(name="complain", help="Takes a complaint and stores it", usage="<message>",
                      description="Delivers a feedback message. "
                                  "The admins and botmasters can then read the accumulated feedback. "
                                  "The bot saves the feedback author, "
                                  "the message and a link to the message for context.")
    async def complain(self, ctx, *args):
        msg = ctx.message
        complaint = Complaint.from_message(self, msg)
        self.complaints[complaint.id] = complaint
        await ctx.message.add_reaction(Lang.CMDSUCCESS)
        self.write()

    """
    Bugscore
    """
    async def bugscore_show(self, ctx):
        users = sorted(
            sorted(
                [(converters.get_best_username(discord.utils.get(self.bot.guild.members, id=user)), n) for (user, n) in
                 self.storage["bugscore"].items()],
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
        if discord.utils.get(ctx.author.roles, id=Config().BOTMASTER_ROLE_ID) is None:
            await ctx.message.add_reaction(Lang.CMDNOPERMISSIONS)
            return
        try:
            user = await commands.MemberConverter().convert(ctx, user)
        except (commands.CommandError, IndexError):
            await ctx.send(Lang.lang(self, "bugscore_user_not_found", user))
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        if user.id in self.storage["bugscore"]:
            del self.storage["bugscore"][user.id]
            Storage.save(self)
            await ctx.message.add_reaction(Lang.CMDSUCCESS)
        else:
            await ctx.message.add_reaction(Lang.CMDNOCHANGE)

    @commands.has_any_role(Config().BOTMASTER_ROLE_ID)
    async def bugscore_increment(self, ctx, user, increment):
        if discord.utils.get(ctx.author.roles, id=Config().BOTMASTER_ROLE_ID) is None:
            await ctx.message.add_reaction(Lang.CMDNOPERMISSIONS)
            return

        # find user
        try:
            user = await commands.MemberConverter().convert(ctx, user)
        except (commands.CommandError, IndexError):
            await ctx.send(Lang.lang(self, "bugscore_user_not_found", user))
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        try:
            increment = int(increment)
        except (ValueError, TypeError):
            await ctx.send(Lang.lang(self, "bugscore_nan", increment))
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        if user.id in self.storage["bugscore"]:
            self.storage["bugscore"][user.id] += increment
        else:
            self.storage["bugscore"][user.id] = increment
        if self.storage["bugscore"][user.id] <= 0:
            del self.storage["bugscore"][user.id]
        Storage.save(self)
        await ctx.message.add_reaction(Lang.CMDSUCCESS)

    @commands.command(name="bugscore", help="High score for users who found bugs",
                      description="Shows the current bug score.\n\n"
                                  "Admins:\n!bugscore <user> [increment]\n!bugscore del <user>")
    async def bugscore(self, ctx, *args):
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
