import calendar
import logging
from datetime import datetime, timedelta

import discord
from discord.ext import commands

from base import BasePlugin
from botutils import restclient
from botutils.stringutils import paginate
from botutils.utils import add_reaction
from subsystems.help import DefaultCategories
from conf import Lang, Config


class Plugin(BasePlugin, name="Sport"):
    """Commands related to soccer or other sports"""

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, category=DefaultCategories.SPORT)
        self.logger = logging.getLogger(__name__)
        self.can_reload = True
        Config().save(self)

    def default_config(self):
        return {
            'sport_chan': 0,
            'leagues': {"bl1": ["bl", "1bl", "buli"], "bl2": ["2bl"], "bl3": ["3fl"], "uefanl": []},
            'liveticker_leagues': ["bl1", "bl2"]
        }

    def default_storage(self):
        return []

    def command_help_string(self, command):
        return Lang.lang(self, "help_{}".format("_".join(command.qualified_name.split())))

    def command_description(self, command):
        name = "_".join(command.qualified_name.split())
        lang_name = "description_{}".format(name)
        result = Lang.lang(self, lang_name)
        if result != lang_name:
            if name == "fußball":
                result = Lang.lang(self, lang_name, ", ".join(Config().get(self)['leagues'].keys()))
        else:
            result = Lang.lang(self, "help_{}".format(name))
        return result

    @commands.command(name="kicker")
    async def kicker_table(self, ctx):
        now = datetime.now()
        if now.month < 3 or now.month > 7:
            at_values = "[{}]({})".format(Lang.lang(self, 'kicker_ATBL'), Lang.lang(self, 'kicker_ATBL_link'))
        else:
            at_values = "[{}]({})\n[{}]({})\n[{}]({})" \
                .format(Lang.lang(self, 'kicker_ATBL'), Lang.lang(self, 'kicker_ATBL_link'),
                        Lang.lang(self, 'kicker_ATBLM'), Lang.lang(self, 'kicker_ATBLM_link'),
                        Lang.lang(self, 'kicker_ATBLQ'), Lang.lang(self, 'kicker_ATBLQ_link'))

        embed = discord.Embed(title=Lang.lang(self, 'kicker_title'))
        embed.add_field(name=Lang.lang(self, 'kicker_DE'),
                        value="[{}]({})\n[{}]({})\n"
                              "[{}]({})\n[{}]({})"
                        .format(Lang.lang(self, 'kicker_1BL'), Lang.lang(self, 'kicker_1BL_link'),
                                Lang.lang(self, 'kicker_2BL'), Lang.lang(self, 'kicker_2BL_link'),
                                Lang.lang(self, 'kicker_3FL'), Lang.lang(self, 'kicker_3FL_link'),
                                Lang.lang(self, 'kicker_DFBP'), Lang.lang(self, 'kicker_DFBP_link')))
        embed.add_field(name=Lang.lang(self, 'kicker_AT'), value=at_values)
        embed.add_field(name=Lang.lang(self, 'kicker_EU'),
                        value="[{}]({})\n[{}]({})".format(
                            Lang.lang(self, 'kicker_CL'), Lang.lang(self, 'kicker_CL_link'),
                            Lang.lang(self, 'kicker_EL'), Lang.lang(self, 'kicker_EL_link')))
        await ctx.send(embed=embed)

    # todo: read directly from sheets
    @commands.command(name="tippspiel")
    async def tippspiel(self, ctx):
        await ctx.send(Lang.lang(self, 'tippspiel_output'))

    @commands.command(name="fußball", aliases=["fusselball"])
    async def soccer_livescores(self, ctx, league, allmatches=None):
        if league not in Config().get(self)['leagues']:
            for leag, aliases in Config().get(self)['leagues'].items():
                if league in aliases:
                    league = leag
                    break
            else:
                await ctx.send(Lang.lang(self, 'league_not_found', ", ".join(Config().get(self)['leagues'])))
                return
        matches = restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/{}".format(league))
        finished, running, upcoming = [], [], []
        for match in matches:
            if match.get('MatchIsFinished', False):
                finished.append(match)
            else:
                try:
                    time = datetime.strptime(match.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
                except (ValueError, TypeError):
                    pass
                else:
                    if time < datetime.now():
                        running.append(match)
                    else:
                        upcoming.append(match)

        def match_msg(m):
            dt = datetime.strptime(m.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
            weekday = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][dt.weekday()]
            time_ = dt.strftime("%H:%M")
            team_h = m.get('Team1', {}).get('TeamName')
            team_a = m.get('Team2', {}).get('TeamName')
            goals = m.get('Goals', [])
            goals_h = max(0, *(x.get('ScoreTeam1', 0) for x in goals)) if len(goals) else ("–" if m in upcoming else 0)
            goals_a = max(0, *(x.get('ScoreTeam2', 0) for x in goals)) if len(goals) else ("–" if m in upcoming else 0)
            return "{}. {} | {} [{}:{}] {}".format(weekday, time_, team_h, goals_h, goals_a, team_a)

        embed = discord.Embed(title=Lang.lang(self, 'soccer_title', league))
        running_msg = "\n".join(match_msg(m) for m in running)
        if running_msg:
            embed.description = "\n".join(match_msg(m) for m in running)
        if allmatches == "all" or not running_msg:
            finished_msg = "\n".join(match_msg(m) for m in finished)
            upcoming_msg = "\n".join(match_msg(m) for m in upcoming)
            if finished_msg:
                embed.add_field(name=Lang.lang(self, 'match_finished'), value=finished_msg, inline=False)
            if upcoming_msg:
                embed.add_field(name=Lang.lang(self, 'match_upcoming'), value=upcoming_msg, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="buli")
    async def buli_livescores(self, ctx, allmatches=None):
        await ctx.invoke(self.bot.get_command('fußball'), 'bl1', allmatches)

    @commands.command(name="buli2")
    async def buli_livescores(self, ctx, allmatches=None):
        await ctx.invoke(self.bot.get_command('fußball'), 'bl2', allmatches)

    @commands.command(name="matches")
    async def matches_24h(self, ctx):
        async with ctx.typing():
            msg = ""
            for league in Config().get(self)['leagues'].keys():
                matches = restclient.Client("https://www.openligadb.de/api").make_request(
                    "/getmatchdata/{}".format(league))
                league_msg = ""
                for match in matches:
                    try:
                        time = datetime.strptime(match.get('MatchDateTime'), "%Y-%m-%dT%H:%M:%S")
                    except (ValueError, TypeError):
                        continue
                    else:
                        now = datetime.now()
                        if not match.get('MatchIsFinished', True) \
                                and now + timedelta(hours=-2) < time < now + timedelta(days=1):
                            league_msg += "{} {} | {} - {}\n".format(
                                calendar.day_abbr[time.weekday()],
                                time.strftime("%H:%M Uhr"),
                                match.get('Team1', {}).get('TeamName'),
                                match.get('Team2', {}).get('TeamName'))
                if league_msg:
                    msg += "{}\n{}\n".format(matches[0].get('LeagueName', league), league_msg)
            if not msg:
                msg = Lang.lang(self, 'no_matches_24h')
        await ctx.send(msg)

    @commands.command(name="liveticker")
    async def liveticker(self, ctx):
        msg = []
        for league in Config().get(self)['liveticker_leagues']:
            liveticker_regs = self.bot.liveticker.search(plugin=self.get_name())
            if league in liveticker_regs:
                for reg in liveticker_regs[league]:
                    reg.deregister()
            reg_ = self.bot.liveticker.register(league=league, plugin=self,
                                                coro=self.live_goals, coro_kickoff=self.live_kickoff,
                                                coro_finished=self.live_finished, periodic=True)
            next_exec = reg_.next_execution()
            if next_exec:
                next_exec = next_exec[0].strftime('%d.%m.%Y - %H:%M')
            msg.append("{} - Next: {}".format(league, next_exec))
        Config().get(self)['sport_chan'] = ctx.channel.id
        Config().save(self)
        await add_reaction(ctx.message, Lang.CMDSUCCESS)
        await ctx.send("\n".join(msg))

    async def live_kickoff(self, match_dicts, league, time):
        sport = Config().bot.get_channel(Config().get(self)['sport_chan'])
        match_msgs = []
        for match in match_dicts:
            match_msgs.append("{} - {}".format(match.get("team_home"), match.get("team_away")))
        msgs = paginate(match_msgs,
                        prefix=Lang.lang(self, 'liveticker_prefix_kickoff', league, time.strftime('%H:%M')))
        for msg in msgs:
            await sport.send(msg)

    async def live_goals(self, new_goals, league, matchminute):
        sport = Config().bot.get_channel(Config().get(self)['sport_chan'])

        matches_with_goals = [x for x in new_goals.values() if x['new_goals'] and not x['is_finished']]
        if matches_with_goals:
            match_msgs = []
            for match in matches_with_goals:
                match_msgs.append(
                    "**{} - {} | {}:{}**".format(match['team_home'], match['team_away'], *match['score']))
                match_goals = []
                for goal in match['new_goals']:
                    minute = goal.get('MatchMinute')
                    if not minute:
                        minute = "?"
                    match_goals.append(
                        "{}:{} {} ({}.)".format(goal.get('ScoreTeam1', "?"), goal.get('ScoreTeam2', "?"),
                                                goal.get('GoalGetterName', "-"), minute))
                match_msgs.append(" / ".join(match_goals))
            msgs = paginate(match_msgs, prefix=Lang.lang(self, 'liveticker_prefix', league, matchminute))
            for msg in msgs:
                await sport.send(msg)
        else:
            await sport.send(Lang.lang(self, 'no_new_goals', league, matchminute))

    async def live_finished(self, match_dicts, league):
        sport = Config().bot.get_channel(Config().get(self)['sport_chan'])
        match_msgs = []
        for match in match_dicts:
            match_msgs.append("{} - {}".format(match.get("team_home"), match.get("team_away")))
        msgs = paginate(match_msgs,
                        prefix=Lang.lang(self, 'liveticker_prefix_finished', league))
        for msg in msgs:
            await sport.send(msg)