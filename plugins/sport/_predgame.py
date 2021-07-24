import datetime
import logging
from itertools import groupby
from operator import itemgetter

import discord
from discord import TextChannel
from discord.ext import commands

from base import BasePlugin
from botutils import restclient, timers, sheetsclient
from botutils.utils import helpstring_helper, add_reaction
from data import Lang, Config, Storage
from subsystems.helpsys import DefaultCategories
from subsystems.liveticker import LivetickerEvent, LivetickerKickoff, LivetickerFinish, Match


class _Predgame:

    # def __init__(self, bot):
    #     super().__init__(bot)
    #     bot.register(self, category=DefaultCategories.SPORT)
    #     self.logger = logging.getLogger(__name__)
    #     self.can_reload = True
    #     self.today_timer = self.bot.timers.schedule(coro=self._today_coro, td=timers.timedict(hour=1, minute=0))
    #
    # def command_help_string(self, command):
    #     return helpstring_helper(self, command, "help")
    #
    # def command_description(self, command):
    #     return helpstring_helper(self, command, "desc")
    #
    # def command_usage(self, command):
    #     return helpstring_helper(self, command, "usage")

    def default_config(self, container=None):
        return {
            "chan_id": 0,
            "show_today_matches": True,
            "overview_sheet": ""
        }

    def default_storage(self, container=None):
        return {}
        # {    "ger.1": {
        #         "name": "Bundesliga",
        #         "sheet": "sheetid"
        #         "name_range": "H1:AE1"  # sheets range in which the names are
        #         "points_range": "H4:AE4"  # sheets range in which the final total points are
        #         "prediction_range": "A1:AE354"  # sheets range in which the prediction data are
        #     }
        # }

    @commands.group(name="predgame", aliases=["tippspiel"], invoke_without_command=True)
    async def cmd_predgame(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command("predgame points"))

    @cmd_predgame.command(name="today")
    async def cmd_today(self, ctx):
        await self._today_matches(ctx.channel)

    async def _today_coro(self, _job):
        if Config.get(self)["show_today_matches"] and Config().get(self)['chan_id']:
            await self._today_matches(Config().bot.get_channel(Config().get(self)['chan_id']))

    async def _today_matches(self, chan: TextChannel):
        """Sends a msg with todays matches to the specified channel

        :param chan: channel object
        """

        for league in Storage.get(self):
            result = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports/soccer")\
                .request(f"/{league}/scoreboard", params={'dates': datetime.datetime.today().strftime("%Y%m%d")})
            msg = [Lang.lang(self, 'today_matches')]

            for m in result.get('events', []):
                match = Match.from_espn(m)
                kickoff = match.kickoff.strftime("%H:%M")
                stadium, city = match.venue
                msg.append(f"{kickoff} | {stadium}, {city} | {match.home_team.emoji} {match.away_team.emoji} "
                           f"{match.home_team.long_name} - {match.away_team.long_name}")
            if len(msg) > 1:
                await chan.send("\n".join(msg))

    async def _liveticker_coro(self, event: LivetickerEvent):
        chan = Config().bot.get_channel(Config().get(self)['chan_id'])
        msg = []
        if isinstance(event, LivetickerKickoff):
            for match in event.matches:
                stadium, city = "?", "?"
                if isinstance(match, Match):
                    stadium, city = match.venue
                msg.append(f"{stadium}, {city} | {match.home_team.emoji} {match.away_team.emoji} "
                           f"{match.home_team.long_name} - {match.away_team.long_name}")
            msg.extend(await self._show_predictions())
        # elif isinstance(event, LivetickerFinish):
        #     for match in event.matches:
        #         msg.append(f"FT {match.score[match.home_team_id]}:{match.score[match.away_team_id]} | "
        #                    f"{match.home_team.emoji} {match.away_team.emoji} "
        #                    f"{match.home_team.long_name} - {match.away_team.long_name}")
        if len(msg) > 1:
            await chan.send("\n".join(msg))

    @cmd_predgame.group(name="sheet", aliases=["sheets"])
    async def cmd_sheet(self, ctx):
        if Config.get(self)["overview_sheet"]:
            msg = "Overview: https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing".format(
                Config.get(self)["overview_sheet"])
            await ctx.send(msg)

        for league in Storage.get(self):
            msg = "{}: https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing".format(
                Storage.get(self)[league]['name'], Storage.get(self)[league]['sheet'])
            await ctx.send(msg)

    @cmd_predgame.command(name="now")
    async def cmd_now(self, ctx):
        msgs = await self._show_predictions()
        if msgs:
            await ctx.send("\n".join(msgs))
        else:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)

    async def _show_predictions(self):
        """Returns a list of the predictions"""
        match_msgs = []
        for league in Storage.get(self):
            c = sheetsclient.Client(self.bot, Config().get(self)['spreadsheet'])
            data = c.get(range=Storage.get(self)[league]["prediction_range"])
            people = [data[0][6 + x*2] for x in range((len(data[0]) - 6) // 2 + 1)]
            now = datetime.datetime.now()
            for row in data[1:]:
                row.extend([None]*(len(data[0]) + 1 - len(row)))
                if row[0] == now.strftime("%d.%m.") and row[1] == now.strftime("%H:%M"):
                    preds = [f"{people[x]} {row[6 + x*2]}:{row[7 + x*2]}" for x in range((len(data[0]) - 6) // 2 + 1)]
                    match_msgs.append(f"{row[3]} - {row[4]} // " + " / ".join(preds))
                elif row[0] and datetime.datetime.strptime(row[0], "%d.%m.") > now:
                    break
        if len(match_msgs) > 0:
            return match_msgs

    @cmd_predgame.command(name="points", aliases=["punkte", "gesamt", "platz"])
    async def cmd_points(self, ctx, league: str = None):
        for leg in Storage.get(self):
            if league is not None and leg != league:
                continue
            c = sheetsclient.Client(self.bot, Storage().get(self)[leg]['sheet'])
            people, points = c.get_multiple([Storage().get(self)[leg]['name_range'],
                                             Storage().get(self)[leg]['points_range']])
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

    @cmd_predgame.command(name="start")
    async def cmd_liveticker_start(self, ctx):
        for league in Storage.get(self):
            await self.bot.livticker.register(league=league, raw_source="espn", plugin=self,
                                              coro=self._liveticker_coro)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_predgame.command(name="stop")
    async def cmd_liveticker_stop(self, ctx):
        result = self.bot.liveticker.search_coro(plugins=[self.get_name()])
        for _, _, c_reg in result:
            c_reg.deregister()
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
