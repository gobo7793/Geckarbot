import logging

from nextcord import Embed
from nextcord.errors import Forbidden, NotFound as NCNotFound

from base.data import Config, Lang
from botutils import converters
from botutils.converters import get_best_username, serialize_channel
from botutils.utils import log_exception, execute_anything_sync, write_debug_channel, send_dm
from plugins.calendar.base import Event, ParseError


class Reminder(Event):
    def __init__(self, plugin, eid, invoke_time, channel, user, text, refpost, msglink):
        """

        :param plugin: Plugin ref
        :param eid: Event ID
        :param invoke_time: Remind time
        :param channel: Channel to post the reminder to
        :param user: User that the reminder is for (author)
        :param text: Reminder message text
        :param refpost: Reference message (if any)
        :param msglink: Cmd message link
        """
        self.logger = logging.getLogger(__name__)
        super().__init__(plugin, eid, invoke_time)

        self.channel = channel
        self.user = user
        self.text = text
        self.msglink = msglink
        self.refpost = refpost

        assert(self.channel is not None, "Channel is None for reminder with id {}".format(self.eid))

    def __str__(self):
        return "<Reminder(Event); channel: {}; user: {}; msglink: {}; refpost: {}>".format(
            self.channel, self.user, self.msglink, self.refpost
        )

    def serialize(self):
        """
        To be serialized (in addition to base event data):
        chan, user, text, msglink, refpost

        :return: Trivially serializable object
        """
        return {
            'chan': serialize_channel(self.channel),
            'user': self.user.id,
            'text': self.text,
            'link': self.msglink,
            'reference': self.refpost.id if self.refpost is not None else None
        }

    @classmethod
    async def deserialize(cls, plugin, eid, invoke_time, obj):
        user = Config().bot.get_user(obj['user'])

        try:
            if obj['chan'] is None:
                raise ParseError
            channel = await converters.deserialize_channel(obj['chan'])

        # Channel Error; build error report embed
        except ParseError as e:
            embed = Embed(title=":x: Reminders error", colour=0xe74c3c)
            embed.description = "Channel for reminder could not be retrieved\n(removing reminder)"
            embed.add_field(name="Reminder id", value=str(eid))

            storage_chan = obj['chan']
            if storage_chan is not None:
                embed.add_field(name="Channel type", value=storage_chan['type'])
                embed.add_field(name="Channel id", value=storage_chan['id'])

            user = converters.get_best_user(obj['user'])
            embed.add_field(name="User", value=converters.get_best_username(user))
            t = obj['time']
            t = "{}-{}-{} {}:{}".format(t.year, t.month, t.day, t.hour, t.minute)
            embed.add_field(name="Remind time", value=t)
            execute_anything_sync(write_debug_channel(embed))
            raise e

        refpost = None
        if obj['reference']:
            try:
                refpost = await channel.fetch_message(obj['reference'])
            except NCNotFound:
                pass

        return cls(plugin, eid, invoke_time, channel, user, obj['text'], refpost, obj['link'])

    async def invoke(self):
        self.logger.debug("Executing reminder '%s'", self)
        self.plugin.explain_history[self.user] = self.msglink

        if self.text:
            remind_text = Lang.lang(self.plugin, 'remind_callback', self.user.mention, self.text)
        else:
            remind_text = Lang.lang(self.plugin, 'remind_callback_no_msg', self.user.mention)

        try:
            try:
                await self.channel.send(remind_text, reference=self.refpost, mention_author=False)
            except Forbidden:
                suffix = Lang.lang(self.plugin, "remind_forbidden_suffix")
                await send_dm(self.user, "{}\n\n{}".format(remind_text, suffix))
        except Exception as e:
            fields = {
                "Recipient": get_best_username(self.user),
                "Channel": self.channel
            }
            await log_exception(e, title=":x: Reminder delivery error", fields=fields)

    def list_entry(self, ctx):
        pass
