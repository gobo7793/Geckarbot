import logging
from datetime import datetime
from typing import Dict, Union

import discord
from discord.ext import commands

from botutils import utils, timeutils, converters
from botutils.timeutils import to_unix_str, TimestampStyle
from data import Storage, Lang
from base import BasePlugin, NotFound
from subsystems import timers
from subsystems.helpsys import DefaultCategories

log = logging.getLogger(__name__)


class Plugin(BasePlugin):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, DefaultCategories.UTILS)
        self.migrate()

        self.reminders = {}  # type: Dict[int, timers.Job]
        utils.execute_anything_sync(self.load_reminders())

        self.explain_history = {}

    def command_help_string(self, command):
        return utils.helpstring_helper(self, command, "help")

    def command_description(self, command):
        return utils.helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return utils.helpstring_helper(self, command, "usage")

    def migrate(self):
        """
        Migrates storage to current version:
            None -> 0: inserts jump link placeholders
            0 -> 1: Change channel serialization
        """
        version = Storage().get(self).get('version', None)
        if version is None:
            Storage().get(self)['version'] = 0
            for rid in Storage().get(self)['reminders'].keys():
                Storage().get(self)['reminders'][rid]['link'] = "Link not found (reminder made on old version)"

        if version == 0:
            Storage().get(self)['version'] = 1
            for rid, reminder in Storage().get(self)['reminders'].items():
                chan = self.bot.get_channel(reminder['chan'])
                if chan is not None:
                    chan = converters.serialize_channel(chan)
                reminder['chan'] = chan

        Storage().save(self)

    def default_storage(self, container=None):
        if container is not None:
            raise NotFound
        return {
            'version': 0,
            'reminders': {}
        }

    async def load_reminders(self):
        """
        Loads the reminders from storage into memory.
        """
        to_remove = []
        for rid, reminder in Storage().get(self)['reminders'].items():
            try:
                if reminder['chan'] is None:
                    raise NotFound
                chan = await converters.deserialize_channel(reminder['chan'])

            # Channel Error
            except NotFound:
                embed = discord.Embed(title=":x: Reminders error", colour=0xe74c3c)
                embed.description = "Channel for reminder could not be retrieved\n(removing reminder)"
                embed.add_field(name="Reminder id", value=str(rid))

                storage_chan = reminder['chan']
                if storage_chan is not None:
                    embed.add_field(name="Channel type", value=storage_chan['type'])
                    embed.add_field(name="Channel id", value=storage_chan['id'])

                user = converters.get_best_user(reminder['user'])
                embed.add_field(name="User", value=converters.get_best_username(user))
                t = reminder['time']
                t = "{}-{}-{} {}:{}".format(t.year, t.month, t.day, t.hour, t.minute)
                embed.add_field(name="Remind time", value=t)
                to_remove.append(rid)
                utils.execute_anything_sync(utils.write_debug_channel(embed))
                continue

            r = self._register_reminder(chan, reminder['user'], reminder['time'],
                                        rid, reminder['text'], reminder['link'], True)
            if not r:
                to_remove.append(r)

        for rid in to_remove:
            self._remove_reminder(rid)

    @commands.group(name="remindme", invoke_without_command=True)
    async def cmd_remindme(self, ctx, *args):
        if not args:
            await ctx.send(Lang.lang(self, 'remind_noargs'))
            return

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
        remind_time = timeutils.parse_time_input(*time_args)

        if remind_time == datetime.max:
            raise commands.BadArgument(message=Lang.lang(self, 'remind_duration_err'))

        reminder_id = max(self.reminders, default=0) + 1

        if remind_time < datetime.now():
            log.debug("Attempted reminder %d in the past: %s", reminder_id, remind_time)
            await ctx.send(Lang.lang(self, 'remind_past'))
            return

        rlink = ctx.message.jump_url
        if self._register_reminder(ctx.channel, ctx.author.id, remind_time, reminder_id, rtext, rlink):
            await ctx.send(Lang.lang(self, 'remind_set', remind_time.strftime('%d.%m.%Y %H:%M'), reminder_id))
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)

    @cmd_remindme.command(name="list")
    async def cmd_reminder_list(self, ctx):
        msg = Lang.lang(self, 'remind_list_prefix')
        reminders_msg = ""
        for job in sorted(self.reminders.values(), key=lambda x: x.next_execution()):
            if job.data['user'] == ctx.author.id:
                if job.data['text']:
                    reminder_text = Lang.lang(self, 'remind_list_message', job.data['text'])
                else:
                    reminder_text = Lang.lang(self, 'remind_list_no_message')
                reminders_msg += Lang.lang(self, 'remind_list_element',
                                           to_unix_str(job.next_execution(), style=TimestampStyle.DATETIME_SHORT),
                                           reminder_text, job.data['id'])

        if not reminders_msg:
            msg = Lang.lang(self, 'remind_list_none')
        await ctx.send(msg + reminders_msg)

    @cmd_remindme.command(name="cancel")
    async def cmd_reminder_cancel(self, ctx, reminder_id: int = -1):
        # remove reminder with id
        if reminder_id >= 0:
            if reminder_id not in self.reminders:
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'remind_del_id_err', reminder_id))
                return
            if self.reminders[reminder_id].data['user'] == ctx.author.id:
                self.reminders[reminder_id].cancel()
                self._remove_reminder(reminder_id)
                await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
                return
            await ctx.send(Lang.lang(self, 'remind_wrong_del'))
            return

        # remove all reminders from user
        to_remove = []
        for key, item in self.reminders.items():
            if item.data['user'] == ctx.author.id:
                to_remove.append(key)
        for el in to_remove:
            self.reminders[reminder_id].cancel()
            self._remove_reminder(el)

        await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_remindme.command(name="explain")
    async def cmd_reminder_explain(self, ctx):
        if ctx.author not in self.explain_history:
            await utils.add_reaction(ctx.message, Lang.CMDNOCHANGE)
            await ctx.send(Lang.lang(self, "explain_notfound"))
            return

        await ctx.send(Lang.lang(self, "explain_message", self.explain_history[ctx.author]))

    def _register_reminder(self, channel: Union[discord.DMChannel, discord.TextChannel, None], user_id: int,
                           remind_time: datetime, reminder_id: int, text, link: str, is_restart: bool = False) -> bool:
        """
        Registers a reminder

        :param channel: The channel in which the reminder was set
        :param user_id: The id of the user who sets the reminder
        :param remind_time: The remind time
        :param reminder_id: The reminder ID
        :param text: The reminder message text
        :param link: The reminder message jump link (or placeholder text)
        :param is_restart: True if reminder is restarting after bot (re)start
        :returns: True if reminder is registered, otherwise False
        """
        if remind_time < datetime.now() and not is_restart:
            log.debug("Attempted reminder %d in the past: %s", reminder_id, remind_time)
            return False

        log.info("Adding reminder %d for user with id %d at %s: %s",
                 reminder_id, user_id, remind_time, text)

        job_data = {
            'chan': channel,
            'user': user_id,
            'time': remind_time,
            'text': text,
            'link': link,
            'id': reminder_id
        }

        timedict = timers.timedict(year=remind_time.year, month=remind_time.month, monthday=remind_time.day,
                                   hour=remind_time.hour, minute=remind_time.minute)
        try:
            job = self.bot.timers.schedule(self._reminder_callback, timedict, data=job_data, repeat=False)
        except timers.NoFutureExec:
            job = timers.Job(self.bot, timedict, self._reminder_callback, data=job_data, repeat=False, run=False)
            utils.execute_anything_sync(self._reminder_callback, job)
            return False

        self.reminders[reminder_id] = job
        if not is_restart:
            Storage().get(self)['reminders'][reminder_id] = job_data.copy()
            Storage().get(self)['reminders'][reminder_id]['chan'] = converters.serialize_channel(job_data['chan'])
            Storage().save(self)

        return True

    def _remove_reminder(self, rid):
        """
        Removes the reminder if in config

        :param rid: the reminder ID
        """
        if rid in self.reminders:
            del self.reminders[rid]
        if rid in Storage().get(self)['reminders']:
            del Storage().get(self)['reminders'][rid]

        Storage().save(self)
        log.debug("Removed reminder %d", rid)

    async def _reminder_callback(self, job):
        log.debug("Executing reminder %d", job.data['id'])

        channel = job.data['chan']
        user = self.bot.get_user(job.data['user'])
        text = job.data['text']
        rid = job.data['id']
        self.explain_history[user] = job.data['link']

        if channel is None:
            raise RuntimeError("Channel is None for reminder with id {}".format(rid))

        if text:
            remind_text = Lang.lang(self, 'remind_callback', user.mention, text)
        else:
            remind_text = Lang.lang(self, 'remind_callback_no_msg', user.mention)

        await channel.send(remind_text)
        self._remove_reminder(rid)
