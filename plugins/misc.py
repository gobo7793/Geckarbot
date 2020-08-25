import random
import logging
import string
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands

import botutils.parsers
from conf import Storage, Lang, Config

from base import BasePlugin
from subsystems import timers, help
from botutils.converters import get_best_username


class Plugin(BasePlugin, name="Funny/Misc Commands"):

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, help.DefaultCategories.MISC)

        self.reminders = {}
        reminders_to_remove = []
        for reminder_id in Storage().get(self)['reminders']:
            reminder = Storage().get(self)['reminders'][reminder_id]
            if not self.register_reminder(reminder['chan'], reminder['user'], reminder['time'],
                                          reminder_id, reminder['text'], True):
                reminders_to_remove.append(reminder_id)
        for el in reminders_to_remove:
            self.remove_reminder(el)

    def default_storage(self):
        return {'reminders': {}}

    def get_new_reminder_id(self):
        """
        Acquires a new reminder id
        :return: free id that can be used for a new timer
        """
        highest = 0
        for el in self.reminders:
            if el >= highest:
                highest = el + 1
        return highest

    @commands.command(name="dice", brief="Simulates rolling dice.",
                      usage="[NumberOfSides] [NumberOfDices]")
    async def dice(self, ctx, number_of_sides: int = 6, number_of_dice: int = 1):
        """Rolls number_of_dice dices with number_of_sides sides and returns the result"""
        dice = [
            str(random.choice(range(1, number_of_sides + 1)))
            for _ in range(number_of_dice)
        ]
        results = ', '.join(dice)
        if len(results) > 2000:
            pos_last_comma = results[:1995].rfind(',')
            results = f"{results[:pos_last_comma + 1]} ..."
        await ctx.send(results)

    @commands.command(name="kicker", help="Returns frequently used links to kicker.de")
    async def kicker_table(self, ctx):
        embed = discord.Embed(title=Lang.lang(self, 'kicker_title'))
        embed.add_field(name=Lang.lang(self, 'kicker_1BL'), value=Lang.lang(self, 'kicker_1BL_link'))
        embed.add_field(name=Lang.lang(self, 'kicker_2BL'), value=Lang.lang(self, 'kicker_2BL_link'))
        embed.add_field(name=Lang.lang(self, 'kicker_3FL'), value=Lang.lang(self, 'kicker_3FL_link'))
        embed.add_field(name=Lang.lang(self, 'kicker_ATBL'), value=Lang.lang(self, 'kicker_ATBL_link'))
        await ctx.send(embed=embed)

    @commands.command(name="choose", help="Picks on of the options. Separate options with '|'",
                      usage="option1 | option2 | ...")
    async def choose(self, ctx, *args):
        full_options_str = " ".join(args)
        if "sabaton" in full_options_str.lower():
            await ctx.send(Lang.lang(self, 'choose_sabaton'))

        options = [i for i in full_options_str.split("|") if i.strip() != ""]
        if len(options) < 1:
            await ctx.send(Lang.lang(self, 'choose_noarg'))
            return
        result = random.choice(options)
        await ctx.send(Lang.lang(self, 'choose_msg') + result.strip())

    @commands.command(name="mud", brief="Pings the bot.")
    async def mud(self, ctx):
        await ctx.send(Lang.lang(self, 'mud_out'))

    @commands.command(name="mudkip", brief="MUDKIP!")
    async def mudkip(self, ctx):
        await ctx.send(Lang.lang(self, 'mudkip_out'))

    @commands.command(name="mimimi", help="Provides an .mp3 file that plays the sound of 'mimimi'.")
    async def mimimi(self, ctx):
        async with ctx.typing():
            file = discord.File(f"{Config().resource_dir(self)}/mimimi.mp3")
            await ctx.send(file=file)

    @commands.command(name="geck", help="GECKARBOR!")
    async def geck(self, ctx):
        async with ctx.typing():
            try:
                file = discord.File(f"{Config().resource_dir(self)}/treecko.jpg")
            except (FileNotFoundError, IsADirectoryError):
                await ctx.message.add_reaction(Lang.CMDERROR)
                return
            await ctx.send(Lang.lang(self, 'geck_out'), file=file)

    @commands.command(name="keysmash", help="VtEGyAuGeAvBVYFSxnfgEpTwIFRUhbUXoMZIdHo")
    async def keysmash(self, ctx):
        msg = "".join(random.choices(string.ascii_letters + string.digits, k=random.randint(25, 50)))
        await ctx.send(msg)

    # todo: read directly from sheets
    @commands.command(name="tippspiel", help="Gives the link to the Tippspiel-Sheet")
    async def tippspiel(self, ctx):
        await ctx.send(Lang.lang(self, 'tippspiel_output'))

    @commands.command(name="werwars", alias="wermobbtgerade", help="Shows which user is bullying other users",
                      description="Shows who is bullying other users in the last 30 minutes in the current channel. "
                                  "Supports ignore list.")
    async def who_mobbing(self, ctx):
        after_date = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(tzinfo=None)
        users = [self.bot.user]
        messages = await ctx.channel.history(after=after_date).flatten()
        for message in messages:
            if message.author not in users:
                users.append(message.author)

        bully = random.choice(users)

        if bully is self.bot.user:
            text = Lang.lang(self, "bully_msg_self")
        else:
            text = Lang.lang(self, "bully_msg", get_best_username(bully))
        await ctx.send(text)

    @commands.command(name="remindme", help="Reminds the author.",
                      usage="<#|#m|#h|#d|DD.MM.YYYY|HH:MM|DD.MM.YYYY HH:MM|DD.MM. HH:MM|cancel|list> "
                            "[message|cancel_id]",
                      description="Reminds the author in x minutes, hours or days or on a fixed date and/or time or "
                                  "cancels the users reminder with given ids.\nThe duration unit can be set with "
                                  "trailing m for minutes, h for hours or d for days. If none is set, the duration "
                                  "unit is in minutes. Duration example: 5h = 5 hours.\nIf no cancel id is given, "
                                  "all user's reminders will be removed.")
    async def reminder(self, ctx, *args):

        # remove hostoric reminders
        old_reminders = []
        for el in self.reminders:
            if (self.reminders[el].next_execution() is None
                    or self.reminders[el].next_execution() < datetime.now()):
                old_reminders.append(el)
        for el in old_reminders:
            self.remove_reminder(el)

        # cancel reminders
        if args[0] == "cancel":
            if len(args) == 2:
                try:
                    remove_id = int(args[1])
                except ValueError:
                    raise commands.BadArgument(message=Lang.lang(self, 'remind_del_id_err'))
            else:
                remove_id = -1

            # remove reminder with id
            if remove_id >= 0:
                if self.reminders[remove_id].data['user'] == ctx.author.id:
                    self.remove_reminder(remove_id)
                    await ctx.message.add_reaction(Lang.CMDSUCCESS)
                    return

                await ctx.send(Lang.lang(self, 'remind_wrong_del'))
                return

            # remove all reminders from user
            to_remove = []
            for el in self.reminders:
                if self.reminders[el].data['user'] == ctx.author.id:
                    to_remove.append(el)
            for el in to_remove:
                self.remove_reminder(el)

            await ctx.message.add_reaction(Lang.CMDSUCCESS)
            return

        # list user's reminders
        if args[0] == "list":
            msg = Lang.lang(self, 'remind_list_prefix')
            reminders_msg = ""
            for job in sorted(self.reminders.values(), key=lambda x: x.next_execution()):
                if job.data['user'] == ctx.author.id:
                    reminders_msg += Lang.lang(self, 'remind_list_element',
                                               job.next_execution().strftime('%d.%m.%Y %H:%M'),
                                               job.data['text'], job.data['id'])

            if not reminders_msg:
                msg = Lang.lang(self, 'remind_list_none')
            await ctx.send(msg + reminders_msg)
            return

        # set reminder
        try:
            datetime.strptime(f"{args[0]} {args[1]}", "%d.%m.%Y %H:%M")
            rtext = " ".join(args[2:])
            time_args = args[0:2]
        except (ValueError, IndexError):
            try:
                datetime.strptime(f"{args[0]} {args[1]}", "%d.%m. %H:%M")
                rtext = " ".join(args[2:])
                time_args = args[0:2]
            except (ValueError, IndexError):
                rtext = " ".join(args[1:])
                time_args = [args[0]]
        remind_time = botutils.parsers.parse_time_input(*time_args)

        if remind_time == datetime.max:
            raise commands.BadArgument(message=Lang.lang(self, 'remind_duration_err'))

        reminder_id = self.get_new_reminder_id()

        if remind_time < datetime.now():
            logging.debug("Attempted reminder {} in the past: {}".format(reminder_id, remind_time))
            await ctx.send(Lang.lang(self, 'remind_past'))
            return

        if self.register_reminder(ctx.channel.id, ctx.author.id, remind_time, reminder_id, rtext):
            await ctx.send(Lang.lang(self, 'remind_set', remind_time.strftime('%d.%m.%Y %H:%M'), reminder_id))
        else:
            await ctx.message.add_reaction(Lang.CMDERROR)

    def register_reminder(self, channel_id: int, user_id: int, remind_time: datetime,
                          reminder_id: int, text, is_restart: bool = False):
        """
        Registers a reminder
        :param channel_id: The id of the channel in which the reminder was set
        :param user_id: The id of the user who sets the reminder
        :param remind_time: The remind time
        :param reminder_id: The reminder ID
        :param text: The reminder message text
        :param is_restart: True if reminder is restarting after bot (re)start
        :returns: True if reminder is registered, otherwise False
        """
        if remind_time < datetime.now():
            logging.debug("Attempted reminder {} in the past: {}".format(reminder_id, remind_time))
            return False

        logging.info("Adding reminder {} for user with id {} at {}: {}".format(reminder_id, user_id,
                                                                               remind_time, text))

        job_data = {'chan': channel_id, 'user': user_id, 'time': remind_time, 'text': text, 'id': reminder_id}

        timedict = timers.timedict(year=remind_time.year, month=remind_time.month, monthday=remind_time.day,
                                   hour=remind_time.hour, minute=remind_time.minute)
        job = self.bot.timers.schedule(self.reminder_callback, timedict, repeat=False)
        job.data = job_data

        self.reminders[reminder_id] = job
        if not is_restart:
            Storage().get(self)['reminders'][reminder_id] = job_data
            Storage().save(self)

        return True

    def remove_reminder(self, reminder_id):
        """
        Removes the reminder if in config
        :param reminder_id: the reminder ID
        """
        if reminder_id in self.reminders:
            self.reminders[reminder_id].cancel()
            del (self.reminders[reminder_id])
        if reminder_id in Storage().get(self)['reminders']:
            del (Storage().get(self)['reminders'][reminder_id])
        Storage().save(self)
        logging.info("Reminder {} removed".format(reminder_id))

    async def reminder_callback(self, job):
        channel = self.bot.get_channel(job.data['chan'])
        user = self.bot.get_user(job.data['user'])
        text = job.data['text']
        rid = job.data['id']
        remind_text = ""
        if text:
            remind_text = Lang.lang(self, 'remind_callback_msg', text)
        await channel.send(Lang.lang(self, 'remind_callback', user.mention, remind_text))
        logging.info("Executed reminder {}".format(rid))
        self.remove_reminder(rid)
