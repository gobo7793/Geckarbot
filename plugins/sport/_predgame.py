import datetime
from itertools import groupby
from operator import itemgetter
from typing import List, Tuple

import discord
from discord import TextChannel
from discord.ext import commands

from botutils import sheetsclient, restclient, timeutils
from botutils.utils import add_reaction
from data import Lang, Config, Storage
from subsystems.liveticker import TeamnameDict, MatchESPN


# pylint: disable=no-member
class _Predgame:

    @commands.group(name="predgame", aliases=["tippspiel"], invoke_without_command=True)
    async def cmd_predgame(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.invoke(self.bot.get_command("predgame points"))

    @cmd_predgame.command(name="today")
    async def cmd_predgame_today(self, ctx):
        match_count = await self._today_matches(ctx.channel)
        if match_count <= 0:
            await ctx.send(Lang.lang(self, "pred_no_today_games"))

    async def _today_coro(self, _job):
        if Config.get(self)["show_today_matches"] and Config().get(self)['sport_chan']:
            await self._today_matches(Config().bot.get_channel(Config().get(self)['sport_chan']))

    async def _today_matches(self, chan: TextChannel) -> int:
        """Sends a msg with todays matches to the specified channel

        :param chan: channel object
        :return: Number of today matches
        """

        match_count = 0
        for league in Storage.get(self)["predictions"]:
            result = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports/soccer") \
                .request(f"/{league}/scoreboard", params={'dates': datetime.datetime.today().strftime("%Y%m%d")})
            msg = [Lang.lang(self, "pred_today_games")]

            for m in result.get('events', []):
                match = MatchESPN(m)
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
    async def cmd_predgame_sheet(self, ctx):
        if Config.get(self)["predictions_overview_sheet"]:
            msg = "Overview: <https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing>".format(
                Config.get(self)["predictions_overview_sheet"])
            await ctx.send(msg)

        for league in Storage.get(self)["predictions"]:
            msg = "{}: <https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing>".format(
                Storage.get(self)["predictions"][league]['name'],
                Storage.get(self)["predictions"][league]['sheet'])
            await ctx.send(msg)

    @cmd_predgame.command(name="preds", aliases=["tipps"])
    async def cmd_predgame_preds(self, ctx, team1: str, team2: str, date: str = None, time: str = None):
        kickoff = None if date is None else timeutils.parse_time_input(date, time)
        team1_dict = self.bot.liveticker.teamname_converter.get(team1)
        team2_dict = self.bot.liveticker.teamname_converter.get(team2)
        if team1_dict is None:
            await ctx.send(Lang.lang(self, "pred_cant_find_team", team1))
            return
        if team2_dict is None:
            await ctx.send(Lang.lang(self, "pred_cant_find_team", team2))
            return

        msg = await self._get_predictions(team1_dict, team2_dict, kickoff)
        if msg:
            await ctx.send(msg)
        else:
            await ctx.send(Lang.lang(self, "pred_cant_find_match", team1_dict.short_name, team2_dict.short_name))

    async def _get_predictions(self, team1: TeamnameDict, team2: TeamnameDict, kickoff: datetime = None) -> str:
        """Returns a list of the predictions for the first found match

        :param kickoff: kickoff datetime object
        :param team1: team1 TeamnameDict object with all its names
        :param team2: team2 TeamnameDict object with all its names
        :return: the predictions output string
        """

        match_msg = ""
        for league in Storage.get(self)["predictions"]:
            c = sheetsclient.Client(self.bot, Storage().get(self)["predictions"][league]['sheet'])
            people_range, data = c.get_multiple([Storage().get(self)["predictions"][league]['name_range'],
                                                 Storage.get(self)["predictions"][league]["prediction_range"]])
            people = [x for x in people_range[0] if x != ""]
            for row in data[1:]:
                row.extend([None] * (len(data[0]) + 1 - len(row)))
                if kickoff is not None and \
                        (row[0] != kickoff.strftime("%d.%m.") or row[1] != kickoff.strftime("%H:%M")):
                    continue
                if not row[2] or not row[5]:
                    continue
                pred_team1 = self.bot.liveticker.teamname_converter.get(row[2])
                pred_team2 = self.bot.liveticker.teamname_converter.get(row[5])
                if pred_team1 is None or pred_team2 is None or \
                        team1.long_name != pred_team1.long_name or team2.long_name != pred_team2.long_name:
                    continue
                preds = ["{} {}:{}".format(people[x], row[6 + x * 2] if row[6 + x * 2] else "-",
                                           row[7 + x * 2] if row[7 + x * 2] else "-")
                         for x in range(len(people))]
                return "{} - {} // {}".format(team1.short_name, team2.short_name, " / ".join(preds))

        return match_msg

    @cmd_predgame.command(name="points", aliases=["punkte", "gesamt", "platz", "total"])
    async def cmd_predgame_points(self, ctx, *args):
        league_args = []
        matchday = 0
        for arg in args:
            try:
                matchday = int(arg)
            except ValueError:
                league_args.append(arg)
        league = " ".join(league_args)

        if matchday <= 0:
            msgs = self._get_total_points(league)
        else:
            msgs = self._get_matchday_points(matchday, league)

        if len(msgs) < 1 and not league:
            await ctx.send(Lang.lang(self, "pred_cant_find_league", league))
        elif len(msgs) < 1 and matchday > 0:
            await ctx.send(Lang.lang(self, "pred_cant_find_matchday", matchday))
        elif len(msgs) < 1 and not league and matchday > 0:
            await ctx.send(Lang.lang(self, "pred_cant_find_league_matchday", league, matchday))
        else:
            for msg in msgs:
                if matchday <= 0:
                    await ctx.send(embed=discord.Embed(title=msg[0], description=msg[1]))
                else:
                    await ctx.send(msg)

    def _get_total_points(self, league: str = "") -> List[Tuple[str, str]]:
        """Return the messages for total points for leagues

        :param league: league to return, if None all leagues will be returned
        :return: The point messages as tuple with title (incl. league name) and description text (points)
        """
        msgs = []
        for leg in Storage.get(self)["predictions"]:
            if league and league not in (leg, Storage.get(self)["predictions"][leg]["name"]):
                continue
            c = sheetsclient.Client(self.bot, Storage().get(self)["predictions"][leg]['sheet'])
            people, points = c.get_multiple([Storage().get(self)["predictions"][leg]['name_range'],
                                             Storage().get(self)["predictions"][leg]['points_range']])
            points_per_person = [x for x in zip(points[0], people[0]) if x != ('', '')]
            points_per_person.sort(reverse=True)
            grouped = [(k, [x[1] for x in v]) for k, v in groupby(points_per_person, key=itemgetter(0))]

            places = ""
            for i in range(3, len(grouped) - 1):
                emote = f"{i + 1}\U0000FE0F\U000020E3" if i < 9 else ":blue_square:"
                places += "\n{} {} - {}".format(emote, grouped[i][0], ", ".join(grouped[i][1]))
            desc = ":trophy: {} - {}\n:second_place: {} - {}\n:third_place: {} - {}{}".format(
                grouped[0][0], ", ".join(grouped[0][1]),
                grouped[1][0], ", ".join(grouped[1][1]),
                grouped[2][0], ", ".join(grouped[2][1]),
                places
            )
            msgs.append((Lang.lang(self, "pred_total_points_title", Storage.get(self)["predictions"][leg]["name"]),
                         desc))
        return msgs

    def _get_matchday_points(self, matchday: int, league: str = "") -> List[str]:
        """Return the messages for points at a specific matchday.

        :param matchday: matchday to return
        :param league: league to return, if None all leagues will be returned
        :return: The point messages
        """
        msgs = []
        for leg in Storage.get(self)["predictions"]:
            if league and league not in (leg, Storage.get(self)["predictions"][leg]["name"]):
                continue
            c = sheetsclient.Client(self.bot, Storage().get(self)["predictions"][leg]['sheet'])
            people_raw, data = c.get_multiple([Storage().get(self)["predictions"][leg]['name_range'],
                                               Storage.get(self)["predictions"][leg]["prediction_range"]])
            for row in data:
                if not row[0].endswith(f" {matchday}"):
                    continue
                points = [x for x in row[1:] if x != ""]
                people = [x for x in people_raw[0] if x != ""]

                people_points = []
                for i in range(len(people)):
                    people_points.append("{} - {}".format(people[i], points[i]))
                msgs.append("{} {} // {}".format(Storage.get(self)["predictions"][leg]["name"],
                                                 row[0], " / ".join(people_points)))
        return msgs

    @cmd_predgame.group(name="set", invoke_without_command=True)
    async def cmd_predgame_set(self, ctx):
        await self.bot.helpsys.cmd_help(ctx, self, ctx.command)

    @cmd_predgame_set.command(name="add")
    async def cmd_predgame_set__add(self, ctx, espn_code, name, sheet_id,
                                    name_range="G1:AD1", points_range="F4:AD4", prediction_range="A1:AD354"):
        Storage.get(self)["predictions"][espn_code] = {
            "name": name,
            "sheet": sheet_id,
            "name_range": name_range,  # sheets range in which the names are
            "points_range": points_range,  # sheets range in which the final total points are
            "prediction_range": prediction_range  # sheets range in which the prediction data are
        }
        Storage.save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_predgame_set.command(name="del")
    async def cmd_predgame_set__del(self, ctx, name):
        if name in Storage.get(self)["predictions"]:
            del Storage.get(self)["predictions"][name]
            Storage.save(self)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDERROR)
            ctx.send(Lang.lang(self, "pred_cant_find_league", name))

    @cmd_predgame_set.command(name="sheet")
    async def cmd_predgame_set_sheet(self, ctx, sheet_id: str = ""):
        Config.get(self)["predictions_overview_sheet"] = sheet_id
        Config.save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
