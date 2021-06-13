import logging

from discord.ext import commands

from base import BasePlugin
from botutils import restclient, timers
from botutils.utils import helpstring_helper, add_reaction
from data import Lang, Config
from subsystems.helpsys import DefaultCategories
from subsystems.liveticker import LivetickerEvent, LivetickerKickoff, LivetickerFinish, Match


class Plugin(BasePlugin, name="EURO2020"):

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, category=DefaultCategories.SPORT)
        self.logger = logging.getLogger(__name__)
        self.can_reload = True
        self.bot.timers.schedule(coro=self.em_today_coro, td=timers.timedict(hour=15, minute=24))

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def default_config(self):
        return {
            'sport_chan': 0
        }

    @commands.group(name="em")
    async def euro2020(self, ctx):
        pass

    @euro2020.command(name="start")
    async def em_liveticker_start(self, ctx):
        Config().get(self)['sport_chan'] = ctx.channel.id
        Config().save(self)
        await self.bot.liveticker.register(league="uefa.euro", raw_source="espn", plugin=self, coro=self._em_coro)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @euro2020.command(name="stop")
    async def em_liveticker_stop(self, ctx):
        result = self.bot.liveticker.search_coro(plugins=[self.get_name()])
        for _, _, c_reg in result:
            c_reg.deregister()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @euro2020.command(name="today")
    async def em_today(self, ctx):
        await self.em_today_matches(ctx)

    async def em_today_coro(self, job):
        if Config().get(self)['sport_chan']:
            await self.em_today_matches(Config().bot.get_channel(Config().get(self)['sport_chan']))

    async def em_today_matches(self, chan):
        result = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports/soccer")\
            .request("/uefa.euro/scoreboard")
        msg = [Lang.lang(self, 'today_matches')]
        for m in result.get('events', []):
            match = Match.from_espn(m)
            kickoff = match.kickoff.strftime("%H:%M")
            stadium, city = match.venue
            msg.append(f"{kickoff} Uhr | {stadium}, {city} | {match.home_team.emoji} {match.away_team.emoji} "
                       f"{match.home_team.long_name} - {match.away_team.long_name}")
        if len(msg) == 1:
            msg.append("None")
        await chan.send("\n".join(msg))

    async def _em_coro(self, event: LivetickerEvent):
        chan = Config().bot.get_channel(Config().get(self)['sport_chan'])
        msg = ["__:soccer: **EURO 2020**__"]
        if isinstance(event, LivetickerKickoff):
            for match in event.matches:
                stadium, city = match.venue
                msg.append(f"{stadium}, {city} | {match.home_team.emoji} {match.away_team.emoji} "
                           f"{match.home_team.long_name} - {match.away_team.long_name}")
        elif isinstance(event, LivetickerFinish):
            for match in event.matches:
                msg.append(f"FT {match.score[match.home_team_id]}:{match.score[match.away_team_id]} | "
                           f"{match.home_team.emoji} {match.away_team.emoji} "
                           f"{match.home_team.long_name} - {match.away_team.long_name}")
        await chan.send("\n".join(msg))