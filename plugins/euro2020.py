import datetime
import logging
from itertools import groupby
from operator import itemgetter

import discord
from discord.ext import commands

from base import BasePlugin
from botutils import restclient, timers, sheetsclient
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
        self.bot.timers.schedule(coro=self.em_today_coro, td=timers.timedict(hour=1, minute=0))

    def command_help_string(self, command):
        return helpstring_helper(self, command, "help")

    def command_description(self, command):
        return helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return helpstring_helper(self, command, "usage")

    def default_config(self):
        return {
            'sport_chan': 0,
            'spreadsheet': "1aPhu_HpThmJ8FOmiaAkdmZWo3WupEV1Qd2-Sju3IxHk",
            'displaysheet': "1yExkjGVSTSTBAxiRplpBMHgX4aVgyNSAZ4lEgBn1XbM",
            'kicker_url': "https://www.kicker.de/europameisterschaft/spieltag"
        }

    @commands.group(name="em")
    async def euro2020(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send(Config().get(self)['kicker_url'])

    @euro2020.command(name="start")
    async def cmd_em_liveticker_start(self, ctx):
        Config().get(self)['sport_chan'] = ctx.channel.id
        Config().save(self)
        await self.bot.liveticker.register(league="uefa.euro", raw_source="espn", plugin=self, coro=self._em_coro)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @euro2020.command(name="stop")
    async def cmd_em_liveticker_stop(self, ctx):
        result = self.bot.liveticker.search_coro(plugins=[self.get_name()])
        for _, _, c_reg in result:
            c_reg.deregister()
            break
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @euro2020.command(name="today")
    async def em_today(self, ctx):
        await self.em_today_matches(ctx)

    async def em_today_coro(self, _job):
        if Config().get(self)['sport_chan']:
            await self.em_today_matches(Config().bot.get_channel(Config().get(self)['sport_chan']))

    async def em_today_matches(self, chan):
        """Sends a msg with todays matches to the specified channel"""
        result = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports/soccer")\
            .request("/uefa.euro/scoreboard", params={'dates': datetime.datetime.today().strftime("%Y%m%d")})
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
                stadium, city = "?", "?"
                if isinstance(match, Match):
                    stadium, city = match.venue
                msg.append(f"{stadium}, {city} | {match.home_team.emoji} {match.away_team.emoji} "
                           f"{match.home_team.long_name} - {match.away_team.long_name}")
            msg.extend(await self.show_emtipp())
        elif isinstance(event, LivetickerFinish):
            for match in event.matches:
                msg.append(f"FT {match.score[match.home_team_id]}:{match.score[match.away_team_id]} | "
                           f"{match.home_team.emoji} {match.away_team.emoji} "
                           f"{match.home_team.long_name} - {match.away_team.long_name}")
        if len(msg) > 1:
            await chan.send("\n".join(msg))

    @commands.group(name="emtipp")
    async def cmd_emtipp(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing".format(
                Config().get(self)['displaysheet']))

    @cmd_emtipp.command(name="now")
    async def cmd_emtipp_now(self, ctx):
        msgs = await self.show_emtipp()
        if not msgs:
            msgs = ["None"]
        await ctx.send("\n".join(msgs))
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    async def show_emtipp(self):
        """Returns a list of the predictions"""
        c = sheetsclient.Client(self.bot, Config().get(self)['spreadsheet'])
        data = c.get(range="B2:AE64")
        people = [data[0][6 + x*2] for x in range((len(data[0]) - 6) // 2 + 1)]
        now = datetime.datetime.now()
        match_msgs = []
        for row in data[1:]:
            row.extend([None]*(len(data[0]) + 1 - len(row)))
            if row[0] == now.strftime("%d.%m.") and row[1] == now.strftime("%H:%M"):
                preds = [f"{people[x]} {row[6 + x*2]}:{row[7 + x*2]}" for x in range((len(data[0]) - 6) // 2 + 1)]
                match_msgs.append(f"{row[3]} - {row[4]} // " + " / ".join(preds))
            elif row[0] and datetime.datetime.strptime(row[0], "%d.%m.") > now:
                break
        return match_msgs

    @cmd_emtipp.command(name="punkte", aliases=["gesamt", "platz"])
    async def cmd_emtipp_points(self, ctx):
        c = sheetsclient.Client(self.bot, Config().get(self)['displaysheet'])
        people, points = c.get_multiple(["J2:AC2", "J67:AC67"])
        points_per_person = [x for x in zip(points[0], people[0]) if x != ('', '')]
        points_per_person.sort(reverse=True)
        grouped = [(k, [x[1] for x in v]) for k, v in groupby(points_per_person, key=itemgetter(0))]
        desc = ":trophy: {} - {}\n:second_place: {} - {}\n:third_place: {} - {}\n{}".format(
            grouped[0][0], ", ".join(grouped[0][1]), grouped[1][0], ", ".join(grouped[1][1]), grouped[2][0],
            ", ".join(grouped[2][1]), " / ".join(["{} - {}".format(
                k, ", ".join(v)
            ) for k, v in grouped[3:]])
        )
        await ctx.send(embed=discord.Embed(title=Lang.lang(self, 'points'), description=desc))