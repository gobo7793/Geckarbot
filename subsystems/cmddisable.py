import datetime
import discord

from conf import Config


class CommandDisable:
    """Manage disabling commands in certain channels
    The cmds and channels will be saved as tuple:
    [0]: command [1]: channel id [2]: expiring time
    """

    def __init__(self, plugin):
        self.plugin = plugin

    def cd_conf(self):
        return Config().get(self.plugin)['disabled_cmds']

    def check_expired(self):
        """Checks all disabled commands and removes expired disablings"""
        to_remove = []
        for cmd_tuple in self.cd_conf():
            if cmd_tuple[2] < datetime.datetime.now():
                to_remove.append(cmd_tuple)

        for removing in to_remove:
            self.cd_conf().remove(removing)

        Config().save(self.plugin)

    def disable(self, command, channel: discord.TextChannel, hours: int = 0):
        """Disables the given command in the given channel for given hours.
        If cmd in channel was now disabled, True will be returned,
        if cmd already disabled in channel False.
        """
        self.check_expired()

        if command.startswith("!"):
            command = command[1:]
        if hours < 1:
            exp_time = datetime.datetime.max
        else:
            exp_time = datetime.datetime.now() + datetime.timedelta(hours=hours)

        is_adding = True
        for t in self.cd_conf():
            if t[0] == command and t[1] == channel.id:
                is_adding = False

        if is_adding:
            self.cd_conf().append((command, channel.id, exp_time))

        Config().save(self.plugin)
        return is_adding

    def enable(self, command, channel: discord.TextChannel):
        """Enables the given command in given channel.
        If cmd is now enabled in given channel, True will be returned, otherwise False.
        """
        self.check_expired()

        if command.startswith("!"):
            command = command[1:]

        to_remove = None
        for t in self.cd_conf():
            if t[0] == command and t[1] == channel.id:
                to_remove = t

        is_removing = False
        if to_remove is not None:
            self.cd_conf().remove(to_remove)
            is_removing = True

        Config().save(self.plugin)
        return is_removing

    def can_cmd_executed(self, command, channel: discord.TextChannel):
        """Returns if command can be executed in given channel"""
        return self.can_cmd_executed_id(command, channel.id)

    def can_cmd_executed_id(self, command, channel_id: int):
        """Returns if command can be executed in channel with given id"""
        self.check_expired()
        current_time = datetime.datetime.now()

        for tp in self.cd_conf():
            if tp[0] == command and tp[1] == channel_id and tp[2] > current_time:
                return False
        return True
