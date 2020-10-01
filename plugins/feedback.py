import logging

import discord.utils
from discord.ext import commands

from base import BasePlugin, NotFound
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

        self.logger = logging.getLogger(__name__)
        self.storage = Storage.get(self)
        self.bugscore = Storage.get(self, container="bugscore")["bugscore"]
        self.complaints = {}
        self.highest_id = None

        if "version" not in self.storage:
            self.storage["version"] = 1
            Storage.save(self)
        self.complaints_version = self.storage["version"]

        for cid in self.storage["complaints"]:
            cid_i = int(cid)
            self.complaints[cid_i] = Complaint.deserialize(self, cid_i, self.storage["complaints"][cid])

        # Migration 2.3 -> 2.4
        if "bugscore" in self.storage:
            self.logger.info("Migrating 2.3 -> 2.4")
            struct = self.default_storage(container="bugscore")
            struct["bugscore"] = self.storage["bugscore"]
            Storage.set(self, struct, container="bugscore")
            del self.storage["bugscore"]
            Storage.save(self)
            Storage.save(self, container="bugscore")
            self.bugscore = Storage.get(self, container="bugscore")["bugscore"]

        self.reset_highest_id()

    def default_storage(self, container=None):
        if container is None:
            return {
                "complaints": {},
                "version": 1,
            }
        elif container == "bugscore":
            return {
                "bugscore": {},
                "version": 1,
            }

    def command_usage(self, command):
        if command.name == "complain":
            return Lang.lang(self, "help_usage_complain")
        else:
            raise NotFound()

    def command_help_string(self, command):
        if command.name == "complain":
            return Lang.lang(self, "help_complain")
        else:
            raise NotFound()

    def command_description(self, command):
        if command.name == "complain":
            return Lang.lang(self, "help_desc_complain")
        else:
            raise NotFound()

    def reset_highest_id(self):
        self.highest_id = 0
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

    def parse_args(self, args, ignore=None):
        ignore = ignore if ignore else []
        ids = []
        cats = []
        for arg in args:
            if arg in ignore:
                continue
            if arg == "last":
                ids.append(len(self.complaints) - 1)
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
                    invoke_without_command=True,
                    help="Redacts the list of complaints (i.e. read and delete)",
                    usage=h_usage,
                    description="Returns the accumulated feedback. Use [del x] to delete feedback #x"
                                "and [full] to include categorized complaints.")
    @commands.has_any_role(Config().ADMIN_ROLE_ID, Config().BOTMASTER_ROLE_ID)
    async def redact(self, ctx, *args):
        aliases = ["all", "full"]
        full = True if len(args) > 0 and args[0] in aliases else False

        # Build complaints list and calculate sums
        ids, cats = self.parse_args(args, ignore=aliases)
        partial = not(len(ids) == 0 and len(cats) == 0)
        complaints = {}
        categorized = 0
        uncategorized = 0
        for index in self.complaints:
            complaint = self.complaints[index]
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

        msgs = [complaints[el].to_message() for el in complaints]

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
        ids, cats = self.parse_args(args)

        # Errors / arg validation
        error = None
        if len(cats) > 1:
            error = Lang.lang(self, "too_many_args")
        else:
            for cid in ids:
                if cid not in self.complaints:
                    error = Lang.lang(self, "redact_cat_complaint_not_found")
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
            else:
                await self.category_show(ctx, cats[0])
                return

        # Move
        else:
            cat = None
            if len(cats) > 0:
                cat = cats[0]
            await self.category_move(ctx, ids, cat)

    @commands.command(name="complain")
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
        if discord.utils.get(ctx.author.roles, id=Config().BOTMASTER_ROLE_ID) is None:
            await ctx.message.add_reaction(Lang.CMDNOPERMISSIONS)
            return
        try:
            user = await commands.MemberConverter().convert(ctx, user)
        except (commands.CommandError, IndexError):
            await ctx.send(Lang.lang(self, "bugscore_user_not_found", user))
            await ctx.message.add_reaction(Lang.CMDERROR)
            return

        if user.id in self.bugscore:
            del self.bugscore[user.id]
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

        if user.id in self.bugscore:
            self.bugscore[user.id] += increment
        else:
            self.bugscore[user.id] = increment
        if self.bugscore[user.id] <= 0:
            del self.bugscore[user.id]
        Storage.save(self, container="bugscore")
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
