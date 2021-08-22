from datetime import datetime, timedelta
import logging
from itertools import groupby
from operator import itemgetter
from typing import List, Tuple, Union

import discord
from discord import TextChannel
from discord.ext import commands

from botutils import sheetsclient, restclient, timeutils
from botutils.converters import get_best_username, get_username_from_id, get_best_user
from botutils.stringutils import paginate, format_andlist
from botutils.utils import add_reaction
from data import Lang, Config, Storage
from subsystems.liveticker import TeamnameDict, MatchESPN

logger = logging.getLogger(__name__)


class _Predgame:

    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="predgame", aliases=["tippspiel"], invoke_without_command=True)
    async def cmd_predgame(self, ctx, *args):
        if len(args) >= 2:
            team1_dict = self.bot.liveticker.teamname_converter.get(args[0])
            team2_dict = self.bot.liveticker.teamname_converter.get(args[1])
            if team1_dict is not None and team2_dict is not None:
                date = args[2] if len(args) >= 3 else None
                time = args[3] if len(args) >= 4 else None

                await ctx.invoke(self.bot.get_command("predgame preds"),
                                 team1_dict.long_name, team2_dict.long_name, date, time)
                return

        await ctx.invoke(self.bot.get_command("predgame points"), *args)

    @cmd_predgame.command(name="today", aliases=["heute"])
    async def cmd_predgame_today(self, ctx):
        async with ctx.channel.typing():
            match_count = await self._today_matches(ctx.channel)

        if match_count <= 0:
            await ctx.send(Lang.lang(self, "pred_no_today_games"))

    async def _today_coro(self, _job):
        today_matches = Config.get(self)["predgame"]["show_today_matches"]
        chan_id = Config().get(self)['sport_chan']
        pinglist = [get_best_user(u) for u in Config.get(self)["predgame"]["pinglist"]]
        if today_matches and chan_id > 0:
            await self._today_matches(Config().bot.get_channel(chan_id), pinglist)

    async def _today_matches(self, chan: TextChannel,
                             pinglist: List[Union[discord.User, discord.Member]] = None) -> int:
        """Sends a msg with todays matches to the specified channel

        :param chan: channel object
        :param pinglist: List of Users/Members to ping in this message
        :return: Number of today matches
        """

        msgs = []
        for league in Storage.get(self)["predictions"]:
            result = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports/soccer") \
                .request(f"/{league}/scoreboard", params={'dates': datetime.today().strftime("%Y%m%d")})

            for m in result.get('events', []):
                match = MatchESPN(m)
                kickoff = match.kickoff.strftime("%H:%M")
                msgs.append(f"{Storage.get(self)['predictions'][league]['name']} | {kickoff} | "
                            f"{match.home_team.emoji} {match.away_team.emoji} "
                            f"{match.home_team.long_name} - {match.away_team.long_name}")

        if len(msgs) > 0:
            ping_msg = ""
            if pinglist is not None and pinglist:
                userlist = format_andlist([user.mention for user in pinglist], ands=Lang.lang(self, 'and'))
                ping_msg = Lang.lang(self, 'pred_today_pinglist', userlist)

            for msg in paginate(msgs,
                                prefix=f"**{Lang.lang(self, 'pred_today_games')}**\n",
                                suffix=f"\n{ping_msg}"):
                await chan.send(msg)

        return len(msgs)

    @cmd_predgame.group(name="sheet", aliases=["sheets", "overview"])
    async def cmd_predgame_sheet(self, ctx):
        msgs = []
        if Config.get(self)["predictions_overview_sheet"]:
            msgs.append(Lang.lang(self, "pred_overview",
                                  "<https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing>"
                                  .format(Config.get(self)["predictions_overview_sheet"])))

        for league in Storage.get(self)["predictions"]:
            msgs.append("{}: <https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing>".format(
                Storage.get(self)["predictions"][league]['name'],
                Storage.get(self)["predictions"][league]['sheet']))

        for msg in paginate(msgs):
            await ctx.send(msg)

    @cmd_predgame.command(name="preds", aliases=["tipps"])
    async def cmd_predgame_preds(self, ctx, team1: str = "", team2: str = "", date: str = None, time: str = None):
        kickoff = None if date is None else timeutils.parse_time_input(date, time)
        team1_dict = self.bot.liveticker.teamname_converter.get(team1)
        team2_dict = self.bot.liveticker.teamname_converter.get(team2)
        if team1_dict is None and team2_dict is not None:
            await ctx.send(Lang.lang(self, "pred_cant_find_team", team1))
            return
        if team1_dict is not None and team2_dict is None:
            await ctx.send(Lang.lang(self, "pred_cant_find_team", team2))
            return

        msg = await self._get_predictions(team1_dict, team2_dict, kickoff)
        if msg:
            await ctx.send(msg)
        elif team1_dict is not None and team2_dict is not None:
            await ctx.send(Lang.lang(self, "pred_cant_find_match", team1_dict.short_name, team2_dict.short_name))
        else:
            pass

    async def _get_predictions(self, team1: TeamnameDict = None, team2: TeamnameDict = None,
                               kickoff: datetime = None) -> str:
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
                # parse data from sheet
                row.extend([None] * (len(data[0]) + 1 - len(row)))
                if kickoff is not None and \
                        (not row[0].endswith(kickoff.strftime("%d.%m.")) or
                         not row[1].endswith(kickoff.strftime("%H:%M"))):
                    continue
                if not row[2] or not row[5]:
                    continue
                pred_team1 = self.bot.liveticker.teamname_converter.get(row[2])
                pred_team2 = self.bot.liveticker.teamname_converter.get(row[5])

                # decide what to show
                if pred_team1 is None or pred_team2 is None:
                    continue
                if team1 is None or team2 is None:
                    now = datetime.now()
                    kickoff_dt = datetime.strptime(f"{row[0][-6:]} {row[1]} {now.year}", "%d.%m. %H:%M %Y")
                    time_diff = now - kickoff_dt
                    if time_diff < timedelta(minutes=-30) or time_diff > timedelta(hours=2):
                        continue

                elif team1.long_name != pred_team1.long_name or team2.long_name != pred_team2.long_name:
                    continue

                # put match into string
                preds = ["{} {}:{}".format(people[x], row[6 + x * 2] if row[6 + x * 2] else "-",
                                           row[7 + x * 2] if row[7 + x * 2] else "-")
                         for x in range(len(people))]
                match_msg += "{} - {} // {}\n".format(pred_team1.short_name, pred_team2.short_name, " / ".join(preds))

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
            people, points_str = c.get_multiple([Storage().get(self)["predictions"][leg]['name_range'],
                                                 Storage().get(self)["predictions"][leg]['points_range']])
            points = []
            pts_format = "d"
            for pts in points_str[0]:
                if not pts:
                    points.append("")
                else:
                    try:
                        points.append(int(pts))
                    except ValueError:
                        pt = pts.replace(",", ".")
                        points.append(float(pt))
                        pts_format = ".3f"
            points_per_person = [x for x in zip(points, people[0]) if x != ('', '')]
            points_per_person.sort(reverse=True)
            grouped = [(k, [x[1] for x in v]) for k, v in groupby(points_per_person, key=itemgetter(0))]

            places = ""
            for i in range(3, len(grouped)):
                emote = f"{i + 1}\U0000FE0F\U000020E3" if i < 9 else \
                    ":keycap_ten:" if i == 9 else ":put_litter_in_its_place:"
                places += "\n{emote} {pts:{pts_format}} - {names}".format(
                    emote=emote, pts=grouped[i][0], pts_format=pts_format, names=", ".join(grouped[i][1]))

            desc = ":trophy: {pts:{pts_format}} - {names}".format(
                pts=grouped[0][0], pts_format=pts_format, names=", ".join(grouped[0][1]))
            if len(grouped) > 1:
                desc += "\n:second_place: {pts:{pts_format}} - {names}".format(
                    pts=grouped[1][0], pts_format=pts_format, names=", ".join(grouped[1][1]))
            if len(grouped) > 2:
                desc += "\n:third_place: {pts:{pts_format}} - {names}".format(
                    pts=grouped[2][0], pts_format=pts_format, names=", ".join(grouped[2][1]))
            desc += places
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
    async def cmd_predgame_set_add(self, ctx, espn_code, name, sheet_id,
                                   name_range="G1:AD1", points_range="G4:AD4", prediction_range="A6:AD345"):
        Storage.get(self)["predictions"][espn_code] = {
            "name": name,
            "sheet": sheet_id,
            "name_range": name_range,  # sheets range in which the names are
            "points_range": points_range,  # sheets range in which the final total points are
            "prediction_range": prediction_range  # sheets range in which the prediction data are
        }
        Storage.save(self)
        logger.info("New prediction league added: %s as %s, using sheet ID %s", espn_code, name, sheet_id)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_predgame_set.command(name="del")
    async def cmd_predgame_set_del(self, ctx, name):
        if name in Storage.get(self)["predictions"]:
            del Storage.get(self)["predictions"][name]
            Storage.save(self)
            logger.info("Prediction league removed: %s", name)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
        else:
            await add_reaction(ctx.message, Lang.CMDERROR)
            ctx.send(Lang.lang(self, "pred_cant_find_league", name))

    @cmd_predgame_set.command(name="sheet", aliases=["overview"])
    async def cmd_predgame_set_sheet(self, ctx, sheet_id: str = ""):
        Config.get(self)["predictions_overview_sheet"] = sheet_id
        Config.save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_predgame_set.command(name="today")
    async def cmd_predgame_set_today(self, ctx, show_today: bool = None):
        if show_today is None:
            current = Config.get(self)["predgame"]["show_today_matches"]
            Config.get(self)["predgame"]["show_today_matches"] = not current
        else:
            Config.get(self)["predgame"]["show_today_matches"] = show_today
        Config.save(self)

        if Config.get(self)["predgame"]["show_today_matches"]:
            await add_reaction(ctx.message, Lang.EMOJI['unmute'])
        else:
            await add_reaction(ctx.message, Lang.EMOJI['mute'])
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_predgame.group(name="pinglist", invoke_without_command=True)
    async def cmd_predgame_pinglist(self, ctx):
        if Config.get(self)["predgame"]["pinglist"]:
            users = ", ".join([get_username_from_id(u) for u in Config.get(self)["predgame"]["pinglist"]])
            await ctx.send(Lang.lang(self, "pred_pinguser_list", users))
        else:
            await ctx.send(Lang.lang(self, "pred_pinguser_empty"))

    @cmd_predgame_pinglist.command(name="add")
    async def cmd_predgame_pinglist_add(self, ctx, user: Union[discord.User, discord.Member]):
        if user.id in Config.get(self)["predgame"]["pinglist"]:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "pred_pinguser_already", get_best_username(user)))
            return

        Config.get(self)["predgame"]["pinglist"].append(user.id)
        Config.save(self)
        logger.info("User %s added to predgame pinglist", user.id)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)

    @cmd_predgame_pinglist.command(name="del")
    async def cmd_predgame_pinglist_del(self, ctx, user: Union[discord.User, discord.Member] = None):
        if user is None:
            Config.get(self)["predgame"]["pinglist"].clear()
            logger.info("All users removed von predgame pinglist")
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            return

        if user.id in Config.get(self)["predgame"]["pinglist"]:
            Config.get(self)["predgame"]["pinglist"].remove(user.id)
            Config.save(self)
            logger.info("User %s removed from predgame pinglist", user.id)
            await add_reaction(ctx.message, Lang.CMDSUCCESS)
            return

        await add_reaction(ctx.message, Lang.CMDERROR)
        await ctx.send(Lang.lang(self, "pred_pinguser_not_found", get_best_username(user)))
