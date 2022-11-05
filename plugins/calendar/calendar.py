import logging
from datetime import datetime
from typing import Dict, Type

from nextcord.ext import commands

from botutils import utils, timeutils, converters
from botutils.timeutils import to_unix_str, TimestampStyle
from botutils.utils import log_exception
from base.data import Storage, Lang, Config
from base.configurable import BasePlugin, NotFound
from plugins.calendar.base import Event, ParseError, ScheduledEvent
from plugins.calendar.reminder import Reminder
from services import timers
from services.helpsys import DefaultCategories

log = logging.getLogger(__name__)


event_type_map: Dict[str, Type[Event]] = {
    "reminder": Reminder
}


class Plugin(BasePlugin, name="calendar"):
    def __init__(self):
        super().__init__()
        Config().bot.register(self, DefaultCategories.UTILS)
        self.migrate()

        self.events = {}  # type: Dict[int, ScheduledEvent]
        utils.execute_anything_sync(self.load_events())

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
            1 -> 2: Added reference
            2 -> 3: Rename reminders to events and introduce types
        """
        version = Storage().get(self).get('version')
        if version is None:
            Storage().get(self)['version'] = 0
            for rid in Storage().get(self)['reminders'].keys():
                Storage().get(self)['reminders'][rid]['link'] = "Link not found (reminder made on old version)"

        if version < 1:
            Storage().get(self)['version'] = 1
            for rid, reminder in Storage().get(self)['reminders'].items():
                chan = Config().bot.get_channel(reminder['chan'])
                if chan is not None:
                    chan = converters.serialize_channel(chan)
                reminder['chan'] = chan

        if version < 2:
            Storage().get(self)['version'] = 2
            for reminder in Storage().get(self)['reminders'].values():
                reminder['reference'] = None

        if version < 3:
            Storage().get(self)['version'] = 3
            if 'reminders' in Storage().get(self):
                Storage().get(self)['events'] = Storage().get(self)['reminders']
                del Storage().get(self)['reminders']
                for event in Storage().get(self)['events'].values():
                    event['type'] = "reminder"

                    # move reminder-specific info into event data
                    data = {}
                    event['data'] = data

                    for el in 'chan', 'user', 'text', 'link', 'reference':
                        data[el] = event[el]
                        del event[el]

        Storage().save(self)

    def default_storage(self, container=None):
        if container is not None:
            raise NotFound
        return {
            'version': 0,
            'reminders': {}
        }

    async def load_events(self):
        """
        Loads all events from storage into memory and queues them.
        """
        to_remove = []
        for eid, event_obj in Storage().get(self).get('events', {}).items():
            event_type = event_type_map.get(event_obj['type'], None)
            if event_type is None:
                await log_exception(ParseError("Event with id {}: Unknown type '{}'".format(eid, event_obj['type'])))
                continue

            try:
                event = await event_type.deserialize(self, eid, event_obj['time'], event_obj['data'])
            except Exception as e:
                await log_exception(e)
                continue

            try:
                self.register_event(eid, event_obj['time'], event, True)
            except timers.NoFutureExec:
                to_remove.append(eid)

        if to_remove:
            for eid in to_remove:
                log.debug("Removing event '{}' (was in the past)".format(eid))
                if 'events' not in Storage.get(self) or eid not in Storage.get(self)['events']:
                    raise RuntimeError("Failed to remove event with the id '{}': not found".format(eid))
                del Storage.get(self)['events'][eid]
            Storage.save(self)

    def get_free_id(self):
        return max(self.events, default=0) + 1

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

        reminder_id = self.get_free_id()

        if remind_time < datetime.now():
            log.debug("Attempted reminder %d in the past: %s", reminder_id, remind_time)
            await ctx.send(Lang.lang(self, 'remind_past'))
            return

        rmd = Reminder(self, reminder_id, remind_time, ctx.channel, ctx.author, rtext,
                       ctx.message.reference.resolved if ctx.message.reference else None, ctx.message.jump_url)
        self.register_event(reminder_id, remind_time, rmd)
        await ctx.send(Lang.lang(self, 'remind_set', to_unix_str(remind_time, style=TimestampStyle.DATETIME_SHORT),
                                 reminder_id))

    @cmd_remindme.command(name="list")
    async def cmd_reminder_list(self, ctx):
        msg = Lang.lang(self, 'remind_list_prefix')
        reminders_msg = ""
        for event in sorted(self.events.values(), key=lambda x: x.job.next_execution(ignore_now=False)):
            job = event.job
            event = event.event
            if not isinstance(event, Reminder):
                continue
            if event.user == ctx.author:
                if event.text:
                    reminder_text = Lang.lang(self, 'remind_list_message', event.text)
                else:
                    reminder_text = Lang.lang(self, 'remind_list_no_message')
                reminders_msg += Lang.lang(self, 'remind_list_element',
                                           to_unix_str(job.next_execution(), style=TimestampStyle.DATETIME_SHORT),
                                           reminder_text, event.eid)

        if not reminders_msg:
            msg = Lang.lang(self, 'remind_list_none')
        await ctx.send(msg + reminders_msg)

    @cmd_remindme.command(name="cancel")
    async def cmd_reminder_cancel(self, ctx, reminder_id: int = -1):
        # remove reminder with id
        if reminder_id >= 0:
            if reminder_id not in self.events or not isinstance(self.events[reminder_id].event, Reminder):
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                await ctx.send(Lang.lang(self, 'remind_del_id_err', reminder_id))
                return
            se = self.events[reminder_id]
            assert isinstance(se.event, Reminder)
            if se.event.user == ctx.author:
                se.job.cancel()
                self._remove_event(se.event)
                await utils.add_reaction(ctx.message, Lang.CMDSUCCESS)
                return
            await ctx.send(Lang.lang(self, 'remind_wrong_del'))
            return
        else:
            await utils.add_reaction(ctx.message, Lang.CMDERROR)

        # remove all reminders from user (removed; todo re-implement or remove this remark)

    @cmd_remindme.command(name="explain")
    async def cmd_reminder_explain(self, ctx):
        if ctx.author not in self.explain_history:
            await utils.add_reaction(ctx.message, Lang.CMDNOCHANGE)
            await ctx.send(Lang.lang(self, "explain_notfound"))
            return

        await ctx.send(Lang.lang(self, "explain_message", self.explain_history[ctx.author]))

    def save_event(self, eid, invoke_time: datetime, event: Event):
        """
        Writes an event to storage.
        :param eid: event ID
        :param invoke_time: event invoke time
        :param event: event object
        """
        if 'events' not in Storage().get(self):
            Storage().get(self)['events'] = {}

        events = Storage().get(self)['events']
        if eid in events:
            raise RuntimeError("Event with id '{}' already exists".format(eid))

        etype = None
        for typekey, typevalue in event_type_map.items():
            if isinstance(event, typevalue):
                etype = typekey
                break
        assert etype is not None, "Event %s, invoke_time '{}': Unknown event type".format(eid, invoke_time)

        events[eid] = {
            'type': etype,
            'time': invoke_time,
            'data': event.serialize()
        }
        Storage.save(self)

    def register_event(self, eid, invoke_time, event: Event, is_restart: bool = False):
        if invoke_time < datetime.now() and not is_restart:
            raise RuntimeError("Attempted to register event %s in the past: %s", event, invoke_time)

        log.info("Registering event %s with invoke time %s", event, invoke_time)
        if eid in self.events:
            raise RuntimeError("Event with id {} alread exists", eid)

        timedict = timers.timedict(year=invoke_time.year, month=invoke_time.month, monthday=invoke_time.day,
                                   hour=invoke_time.hour, minute=invoke_time.minute)
        try:
            job = Config().bot.timers.schedule(self._event_callback, timedict, data=event, repeat=False)
        except timers.NoFutureExec as e:
            utils.execute_anything_sync(event.invoke)
            raise e

        self.events[eid] = ScheduledEvent(event, job)
        if not is_restart:
            self.save_event(eid, invoke_time, event)

    def _remove_event(self, event: Event):
        """
        Removes event from the queue.
        :param event:
        :return:
        """
        for eid, se in self.events.items():
            if se.event == event:
                del self.events[eid]
                if eid in Storage().get(self)['events']:
                    del Storage().get(self)['events'][eid]
                    Storage().save(self)
                return
        raise RuntimeError("Failed to remove event '{}' from queue: not found".format(event))

    async def _event_callback(self, job):
        event: Event = job.data
        try:
            self._remove_event(event)
        finally:
            await event.invoke()
