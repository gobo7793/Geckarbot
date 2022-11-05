import abc
from dataclasses import dataclass

from services.timers import Job


class ParseError(Exception):
    pass


class ListingNotPermitted:
    """
    Raised by Event.list_entry() if the event is not to be listed
    """
    pass


class Event:
    @abc.abstractmethod
    def __init__(self, plugin, eid, invoke_time):
        self.plugin = plugin
        self.eid = eid
        self.invoke_time = invoke_time

    def serialize(self):
        pass

    @classmethod
    @abc.abstractmethod
    async def deserialize(cls, plugin, eid, invoke_time, obj):
        """
        :param plugin: Plugin ref
        :param eid: Event ID
        :param invoke_time: Datetime at which this event is going to be invoked
        :param obj: dict representing the event to be deserialized
        :return: Event
        """
        pass

    @abc.abstractmethod
    async def invoke(self):
        """
        Is called on the registered invoke time.
        """
        pass

    @abc.abstractmethod
    def list_entry(self, ctx):
        """
        String that is used as a listing entry for this event.

        :param ctx: Context
        """
        pass


@dataclass
class ScheduledEvent:
    event: Event
    job: Job
