import logging
import asyncio
import random
from enum import Enum

import discord
from discord.ext import commands

from Geckarbot import BasePlugin
from conf import Config
from botutils import utils, statemachine


jsonify = {
    "register_timeout": 1,
}


h_help = "Wer bin ich?"
h_description = "Startet ein Wer bin ich?. Nach einer Registrierungsphase ordne ich jedem Spieler einen zufälligen " \
                "anderen Spieler zu, für den dieser per PN einen zu erratenden Namen angeben darf. Das " \
                "(spoilerfreie) Ergebnis wird ebenfalls jedem Spieler per PN mitgeteilt."
h_usage = ""
h_spoiler = "Zuschauer-Kommando, mit dem diese das letzte Spiel erfragen können."
h_clear = "Entfernt das letzte Spiel, sodass !werbinich spoiler nichts zurückgibt."


class State(Enum):
    IDLE = 0  # no whoami running
    REGISTER = 1  # registering phase
    COLLECT = 2  # messaging everyone and waiting for entries from participants
    DELIVER = 3  # messaging results to everyone
    ABORT = 4  # not everyone answered


class Participant:
    def __init__(self, plugin, user):
        self.plugin = plugin
        self.user = user
        self.assigned = None  # user this one has to choose for
        self.chosen = None
        self.registration = None
        self.plugin.logger.debug("New Participant: {}".format(user))

    def assign(self, p):
        """
        Assigns a participant. Can only be called once.
        :param p: Participant this one has to choose for
        """
        if self.assigned is not None:
            raise RuntimeError("This participant already has an assigned participant")
        self.plugin.logger.debug("Assigning {} to {}".format(p, self.user))
        self.assigned = p

    async def init_dm(self):
        self.plugin.logger.debug("Sending init DM to {}".format(self.user))
        self.registration = self.plugin.bot.dm_listener.register(self.user, self.dm_callback)
        await self.send(Config.lang(self.plugin, "ask_for_entry", utils.get_best_username(self.assigned.user)))

    async def dm_callback(self, cb, message):
        self.plugin.logger.debug("Incoming message from {}: {}".format(self.user, message.content))
        if message.content.strip() == "":
            # you never know
            return

        if self.plugin.statemachine.state != State.COLLECT:
            await self.send(Config.lang(self.plugin, "entry_too_late"))

        first = True
        if self.chosen:
            first = False

        self.chosen = message.content
        if first:
            await self.send(Config.lang(self.plugin, "entry_done", utils.get_best_username(self.assigned.user),
                                        self.chosen))
        else:
            await self.send(Config.lang(self.plugin, "entry_change", self.chosen))

        self.plugin.assigned()

    async def send(self, msg):
        self.plugin.logger.debug("Sending DM to {}: {}".format(self.user, msg))
        return await self.user.send(msg)

    def to_msg(self):
        return "**{}**: {} (von {})".format(utils.get_best_username(self.assigned.user), self.chosen,
                                            utils.get_best_username(self.user))

    def cleanup(self):
        self.plugin.logger.debug("Cleaning up participant {}".format(self.user))
        if self.registration is not None:
            self.registration.unregister()
            self.registration = None

    def __str__(self):
        return "<Participant object for user '{}'>".format(self.user)


class Plugin(BasePlugin, name="Wer bin ich?"):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)
        self.logger = logging.getLogger(__name__)
        self.config = jsonify

        self.channel = None
        self.initiator = None
        self.participants = []

        self.statemachine = statemachine.StateMachine()
        self.statemachine.add_state(State.IDLE, None)
        self.statemachine.add_state(State.REGISTER, self.registering_phase, [State.IDLE])
        self.statemachine.add_state(State.COLLECT, self.collecting_phase, [State.REGISTER])
        self.statemachine.add_state(State.DELIVER, self.delivering_phase, [State.COLLECT])

        self.statemachine.add_state(State.ABORT, self.abort)
        self.statemachine.state = State.IDLE

    @commands.group(name="werbinich", invoke_without_command=True,
                    help=h_help, description=h_description, usage=h_usage)
    async def whoami(self, ctx):
        if self.statemachine.state != State.IDLE:
            await ctx.send(Config.lang(self, "already_running"))
            return

        self.channel = ctx.channel
        self.initiator = ctx.message.author
        self.statemachine.state = State.REGISTER

    @whoami.command(name="status")
    async def statuscmd(self, ctx):
        if self.statemachine.state == State.IDLE:
            await ctx.send(Config.lang(self, "not_running"))
            return
        elif self.statemachine.state == State.REGISTER:
            await ctx.send(Config.lang(self, "status_aborting"))
            return
        elif self.statemachine.state == State.DELIVER:
            await ctx.send(Config.lang(self, "status_delivering"))
            return
        elif self.statemachine.state == State.ABORT:
            await ctx.send(Config.lang(self, "status_aborting"))
            return

        assert self.statemachine.state == State.COLLECT
        waitingfor = []
        for el in self.participants:
            if el.chosen is None:
                waitingfor.append(utils.get_best_username(el.user))

        wf = utils.format_andlist(waitingfor, ands=Config.lang(self, "and"), emptylist=Config.lang(self, "nobody"))
        await ctx.send(Config.lang(self, "waiting_for", wf))

    @whoami.command(name="stop")
    async def stopcmd(self, ctx):
        if self.statemachine.state == State.IDLE:
            await ctx.message.add_reaction(Config().CMDERROR)
            await ctx.send(Config.lang(self, "not_running"))
            return
        await ctx.message.add_reaction(Config().CMDSUCCESS)
        self.cleanup()

    @whoami.command(name="spoiler", help=h_spoiler)
    async def spoilercmd(self, ctx):
        # State check
        error = None
        if self.statemachine.state != State.IDLE:
            error = "show_running"

        elif not self.participants:
            error = "show_not_found"

        elif ctx.author in [x.user for x in self.participants]:
            error = "no_spoiler"

        if error is not None:
            await ctx.message.add_reaction(Config().CMDERROR)
            await ctx.send(Config.lang(self, error))
            return

        await ctx.message.add_reaction(Config().CMDSUCCESS)
        for msg in utils.paginate(self.participants, prefix=Config.lang(self, "participants_last_round"),
                                  f=lambda x: x.to_msg()):
            await ctx.author.send(msg)

    @whoami.command(name="fertig", help=h_clear)
    async def clearcmd(self, ctx):
        if not self.participants:
            await ctx.message.add_reaction(Config().CMDERROR)
            return
        self.participants = []
        await ctx.message.add_reaction(Config().CMDSUCCESS)

    """
    Transitions
    """
    async def registering_phase(self):

        self.logger.debug("Starting registering phase")
        self.statemachine.state = State.REGISTER
        reaction = Config.lang(self, "reaction_signup")
        to = self.config["register_timeout"]
        msg = Config.lang(self, "registering", reaction, to,
                          utils.sg_pl(to, Config.lang(self, "minute_sg"), Config.lang(self, "minute_pl")))
        msg = await self.channel.send(msg)
        await msg.add_reaction(Config.lang(self, "reaction_signup"))

        await asyncio.sleep(to * 60)

        # Consume signup reactions
        self.participants = []
        await msg.remove_reaction(Config.lang(self, "reaction_signup"), self.bot.user)
        signup_msg = discord.utils.get(self.bot.cached_messages, id=msg.id)
        reaction = None
        for el in signup_msg.reactions:
            if el.emoji == Config.lang(self, "reaction_signup"):
                reaction = el
                break

        if reaction is not None:
            async for user in reaction.users():
                if user == self.bot.user:
                    continue

                self.participants.append(Participant(self, user))

        players = len(self.participants)
        if players <= 1:
            await self.channel.send(Config.lang(self, "no_participants"))
            self.statemachine.state = State.ABORT
        else:
            self.statemachine.state = State.COLLECT

    async def collecting_phase(self):
        assert len(self.participants) > 1

        msg = [utils.get_best_username(el.user) for el in self.participants]
        msg = utils.format_andlist(msg, ands=Config.lang(self, "and"))
        msg = Config.lang(self, "list_participants", msg)
        await self.channel.send(msg)

        shuffled = self.participants.copy()
        utils.trueshuffle(shuffled)
        for i in range(len(self.participants)):
            self.participants[i].assign(shuffled[i])

        for el in self.participants:
            await el.init_dm()

    def assigned(self):
        for el in self.participants:
            if el.chosen is None:
                return
        self.statemachine.state = State.DELIVER

    async def delivering_phase(self):
        for target in self.participants:
            todo = []
            for el in self.participants:
                if el.assigned != target:
                    todo.append(el.to_msg())

            for msg in utils.paginate(todo, prefix=Config.lang(self, "list_title")):
                await target.send(msg)
        await self.channel.send(Config.lang(self, "done"))
        self.cleanup()
        self.statemachine.state = State.IDLE

    async def abort(self):
        self.cleanup()
        self.statemachine.state = State.IDLE

    def cleanup(self):
        for el in self.participants:
            el.cleanup()
        self.initiator = None
        self.channel = None
        self.statemachine.state = State.IDLE
