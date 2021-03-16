import locale
import random
import logging
import string
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands

import botutils.timeutils
from botutils import restclient, utils
from data import Storage, Lang, Config

from base import BasePlugin, NotFound
from subsystems import timers, help
from botutils.converters import get_best_username

log = logging.getLogger(__name__)
keysmash_cmd_name = "keysmash"


def _create_keysmash():
    return "".join(random.choices(string.ascii_lowercase, k=random.randint(25, 35)))


class Plugin(BasePlugin, name="Funny/Misc Commands"):

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, help.DefaultCategories.MISC)

        self.reminders = {}
        reminders_to_remove = []
        for reminder_id in Storage().get(self)['reminders']:
            reminder = Storage().get(self)['reminders'][reminder_id]
            if not self._register_reminder(reminder['chan'], reminder['user'], reminder['time'],
                                           reminder_id, reminder['text'], True):
                reminders_to_remove.append(reminder_id)
        for el in reminders_to_remove:
            self._remove_reminder(el)

        # Add commands to help category 'utils'
        to_add = ("dice", "choose", "remindme", "multichoose", "money")
        for cmd in self.get_commands():
            if cmd.name in to_add:
                self.bot.helpsys.default_category(help.DefaultCategories.UTILS).add_command(cmd)
                self.bot.helpsys.default_category(help.DefaultCategories.MISC).remove_command(cmd)

    def default_storage(self):
        return {'reminders': {}}

    def command_help_string(self, command):
        if command.name == keysmash_cmd_name:
            return _create_keysmash()

        langstr = Lang.lang_no_failsafe(self, "help_{}".format(command.qualified_name.replace(" ", "_")))
        if langstr is not None:
            return langstr
        else:
            raise NotFound()

    def command_description(self, command):
        langstr = Lang.lang_no_failsafe(self, "help_desc_{}".format(command.qualified_name.replace(" ", "_")))
        if langstr is not None:
            return langstr
        else:
            raise NotFound()

    def command_usage(self, command):
        langstr = Lang.lang_no_failsafe(self, "help_usage_{}".format(command.qualified_name.replace(" ", "_")))
        if langstr is not None:
            return langstr
        else:
            raise NotFound()

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

    @commands.command(name="dice")
    async def dice(self, ctx, number_of_sides: int = 6, number_of_dice: int = 1):
        """Rolls number_of_dice dices with number_of_sides sides and returns the result"""
        dice = [
            str(random.choice(range(1, number_of_sides + 1)))
            for _ in range(number_of_dice)
        ]
        results = ', '.join(dice)
        if len(results) > 2000:
            pos_last_comma = results[:1998].rfind(',')
            results = f"{results[:pos_last_comma + 1]}\u2026"
        await ctx.send(results)

    @commands.command(name="choose")
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

    @commands.command(name="multichoose")
    async def multichoose(self, ctx, count: int, *args):
        full_options_str = " ".join(args)
        options = [i for i in full_options_str.split("|") if i.strip() != ""]
        if count < 1 or len(options) < count:
            await ctx.send(Lang.lang(self, 'choose_falsecount'))
            return
        result = random.sample(options, k=count)
        await ctx.send(Lang.lang(self, 'choose_msg') + ", ".join(x.strip() for x in result))

    @commands.command(name="mud")
    async def mud(self, ctx):
        await ctx.send(Lang.lang(self, 'mud_out'))

    @commands.command(name="mudkip")
    async def mudkip(self, ctx):
        await ctx.send(Lang.lang(self, 'mudkip_out'))

    @commands.command(name="mimimi")
    async def mimimi(self, ctx):
        async with ctx.typing():
            file = discord.File(f"{Config().resource_dir(self)}/mimimi.mp3")
            await ctx.send(file=file)

    @commands.command(name="money")
    async def money_converter(self, ctx, currency, arg2=None, arg3: float = None):
        currency = currency.upper()
        if arg3:
            amount = arg3
            other_curr = arg2.upper()
        elif arg2:
            try:
                amount = float(arg2)
            except (TypeError, ValueError):
                other_curr = arg2.upper()
                amount = 1
            else:
                other_curr = "EUR"
        else:
            amount = 1
            other_curr = "EUR"
        rates = restclient.Client("https://api.exchangeratesapi.io").make_request("/latest")
        rate1 = rates.get('rates', {}).get(currency) if currency != "EUR" else 1
        rate2 = rates.get('rates', {}).get(other_curr) if other_curr != "EUR" else 1
        if rate1 and rate2:
            print(f"{amount:n}")
            other_amount = float(rate2) / float(rate1) * amount
            await ctx.send(Lang.lang(self, 'money_converted',
                                     locale.format_string('%.2f', amount, grouping=True), currency,
                                     locale.format_string('%.2f', other_amount, grouping=True), other_curr))
        else:
            await ctx.send(Lang.lang(self, 'money_error'))

    @commands.command(name="geck")
    async def geck(self, ctx):
        treecko_file = f"{Config().resource_dir(self)}/treecko.jpg"
        async with ctx.typing():
            try:
                file = discord.File(treecko_file)
            except (FileNotFoundError, IsADirectoryError):
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                await utils.write_debug_channel(Lang.lang(self, 'geck_error', treecko_file))
                return
        await ctx.send(Lang.lang(self, 'geck_out'), file=file)

    @commands.command(name=keysmash_cmd_name)
    async def keysmash(self, ctx):
        msg = _create_keysmash()
        await ctx.send(msg)

    @commands.command(name="werwars", alsiases=["wermobbtgerade"])
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

    @commands.group(name="remindme", invoke_without_command=True)
    async def reminder(self, ctx, *args):
        self._remove_old_reminders()

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
        remind_time = botutils.timeutils.parse_time_input(*time_args)

        if remind_time == datetime.max:
            raise commands.BadArgument(message=Lang.lang(self, 'remind_duration_err'))

        reminder_id = self.get_new_reminder_id()

        if remind_time < datetime.now():
            log.debug("Attempted reminder {} in the past: {}".format(reminder_id, remind_time))
            await ctx.send(Lang.lang(self, 'remind_past'))
            return

        if self._register_reminder(ctx.channel.id, ctx.author.id, remind_time, reminder_id, rtext):
            await ctx.send(Lang.lang(self, 'remind_set', remind_time.strftime('%d.%m.%Y %H:%M'), reminder_id))
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)

    @reminder.command(name="list")
    async def reminder_list(self, ctx):
        self._remove_old_reminders()

        msg = Lang.lang(self, 'remind_list_prefix')
        reminders_msg = ""
        for job in sorted(self.reminders.values(), key=lambda x: x.next_execution()):
            if job.data['user'] == ctx.author.id:
                if job.data['text']:
                    reminder_text = Lang.lang(self, 'remind_list_message', job.data['text'])
                else:
                    reminder_text = Lang.lang(self, 'remind_list_no_message')
                reminders_msg += Lang.lang(self, 'remind_list_element',
                                           job.next_execution().strftime('%d.%m.%Y %H:%M'),
                                           reminder_text, job.data['id'])

        if not reminders_msg:
            msg = Lang.lang(self, 'remind_list_none')
        await ctx.send(msg + reminders_msg)

    @reminder.command(name="cancel")
    async def reminder_cancel(self, ctx, reminder_id: int = -1):
        self._remove_old_reminders()

        # remove reminder with id
        if reminder_id >= 0:
            if reminder_id not in self.reminders:
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'remind_del_id_err', reminder_id))
                return
            if self.reminders[reminder_id].data['user'] == ctx.author.id:
                self._remove_reminder(reminder_id)
                await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
                return
            await ctx.send(Lang.lang(self, 'remind_wrong_del'))
            return

        # remove all reminders from user
        to_remove = []
        for el in self.reminders:
            if self.reminders[el].data['user'] == ctx.author.id:
                to_remove.append(el)
        for el in to_remove:
            self._remove_reminder(el)

        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    def _register_reminder(self, channel_id: int, user_id: int, remind_time: datetime,
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
            log.debug("Attempted reminder {} in the past: {}".format(reminder_id, remind_time))
            return False

        log.info("Adding reminder {} for user with id {} at {}: {}".format(reminder_id, user_id,
                                                                               remind_time, text))

        job_data = {'chan': channel_id, 'user': user_id, 'time': remind_time, 'text': text, 'id': reminder_id}

        timedict = timers.timedict(year=remind_time.year, month=remind_time.month, monthday=remind_time.day,
                                   hour=remind_time.hour, minute=remind_time.minute)
        job = self.bot.timers.schedule(self._reminder_callback, timedict, repeat=False)
        job.data = job_data

        self.reminders[reminder_id] = job
        if not is_restart:
            Storage().get(self)['reminders'][reminder_id] = job_data
            Storage().save(self)

        return True

    def _remove_old_reminders(self):
        """
        Auto-Removes all reminders in the past
        """
        old_reminders = []
        for el in self.reminders:
            if (self.reminders[el].next_execution() is None
                    or self.reminders[el].next_execution() < datetime.now()):
                old_reminders.append(el)
        for el in old_reminders:
            self._remove_reminder(el)

    def _remove_reminder(self, reminder_id):
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
        log.info("Reminder {} removed".format(reminder_id))

    async def _reminder_callback(self, job):
        channel = self.bot.get_channel(job.data['chan'])
        user = self.bot.get_user(job.data['user'])
        text = job.data['text']
        rid = job.data['id']
        if text:
            remind_text = Lang.lang(self, 'remind_callback', user.mention, text)
        else:
            remind_text = Lang.lang(self, 'remind_callback_no_msg', user.mention)
        await channel.send(remind_text)
        log.info("Executed reminder {}".format(rid))
        self._remove_reminder(rid)
