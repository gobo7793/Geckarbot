import datetime
from itertools import groupby
from operator import itemgetter

import discord
from discord import TextChannel
from discord.ext import commands

from botutils import sheetsclient, restclient
from botutils.utils import add_reaction
from data import Lang, Config, Storage
from subsystems.liveticker import Match


class _Predgame:

    @commands.group(name="predgame", aliases=["tippspiel"], invoke_without_command=True)
    async def cmd_predgame(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command("predgame points"))

    @cmd_predgame.command(name="today")
    async def cmd_today(self, ctx):
        match_count = await self._today_matches(ctx.channel)
        if match_count <= 0:
            await add_reaction(ctx.message, Lang.CMDNOCHANGE)

    async def _today_coro(self, _job):
        if Config.get(self)["show_today_matches"] and Config().get(self)['sport_chan']:
            await self._today_matches(Config().bot.get_channel(Config().get(self)['sport_chan']))

    async def _today_matches(self, chan: TextChannel):
        """Sends a msg with todays matches to the specified channel

        :param chan: channel object
        :return: Number of today matches
        """

        match_count = 0
        for league in Storage.get(self)["predictions"]:
            result = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports/soccer")\
                .request(f"/{league}/scoreboard", params={'dates': datetime.datetime.today().strftime("%Y%m%d")})
            msg = ["Tippspiel - Heutige Spiele"]

            for m in result.get('events', []):
                match = Match.from_espn(m)
                kickoff = match.kickoff.strftime("%H:%M")
                stadium, city = match.venue
                msg.append(f"{Storage.get(self)['predictions'][league]['name']} | {kickoff} | {stadium}, {city} | "
                           f"{match.home_team.emoji} {match.away_team.emoji} "
                           f"{match.home_team.long_name} - {match.away_team.long_name}")

            match_count += len(msg)
            if len(msg) > 1:
                await chan.send("\n".join(msg))

        return match_count

    @cmd_predgame.group(name="sheet", aliases=["sheets"])
    async def cmd_sheet(self, ctx):
        if Config.get(self)["predictions_overview_sheet"]:
            msg = "Overview: https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing".format(
                Config.get(self)["predictions_overview_sheet"])
            await ctx.send(msg)

        for league in Storage.get(self)["predictions"]:
            msg = "{}: https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing".format(
                Storage.get(self)["predictions"][league]['name'],
                Storage.get(self)["predictions"][league]['sheet'])
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
        for league in Storage.get(self)["predictions"]:
            c = sheetsclient.Client(self.bot, Config().get(self)['spreadsheet'])
            data = c.get(range=Storage.get(self)["predictions"][league]["prediction_range"])
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
        for leg in Storage.get(self)["predictions"]:
            if league is not None and leg != league:
                continue
            c = sheetsclient.Client(self.bot, Storage().get(self)["predictions"][leg]['sheet'])
            people, points = c.get_multiple([Storage().get(self)["predictions"][leg]['name_range'],
                                             Storage().get(self)["predictions"][leg]['points_range']])
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
