import calendar
from datetime import datetime, timedelta

import discord
from discord.ext import commands

from botutils import restclient
from botutils.utils import add_reaction
from data import Lang, Config
from subsystems.liveticker import LTSource, MatchStatus, MatchOLDB, MatchESPN, MatchBase


class _Scores:

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="kicker")
    async def cmd_kicker_table(self, ctx):
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

    @commands.command(name="fußball", aliases=["fusselball"])
    async def cmd_soccer_livescores(self, ctx, league: str, raw_source: str = None, allmatches=None):
        if raw_source is None:
            # Look for alts
            league, raw_source = Config().get(self)['league_aliases'].get(league, (league, "espn"))
        try:
            source = LTSource(raw_source)
        except ValueError:
            await ctx.send(Lang.lang(self, 'source_not_found', ", ".join(s.value for s in LTSource)))
            return

        if source == LTSource.OPENLIGADB:
            try:
                raw_matches = await restclient.Client("https://www.openligadb.de/api") \
                    .request(f"/getmatchdata/{league}")
                matches = [MatchOLDB(m) for m in raw_matches]
            except (ValueError, AttributeError):
                await add_reaction(ctx.message, Lang.CMDERROR)
                return
        elif source == LTSource.ESPN:
            raw_matches = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports").request(
                f"/soccer/{league}/scoreboard", params={'dates': datetime.today().strftime("%Y%m%d")})
            matches = [MatchESPN(m) for m in raw_matches.get('events', [])]
        else:
            await ctx.send(Lang.lang(self, 'source_not_supported', source))
            return

        if len(matches) == 0:
            await ctx.send(Lang.lang(self, 'no_matches_found'))
            return
        finished = [m for m in matches if m.status == MatchStatus.COMPLETED]
        running = [m for m in matches if m.status == MatchStatus.RUNNING]
        upcoming = [m for m in matches if m.status == MatchStatus.UPCOMING]

        def match_msg(m: MatchBase):
            weekday = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][m.kickoff.weekday()]
            time_ = m.kickoff.strftime("%H:%M")
            team_h = m.home_team.long_name
            team_a = m.away_team.long_name
            goals_h = m.score[m.home_team_id]
            goals_a = m.score[m.away_team_id]
            return "{}. {} | {} [{}:{}] {}".format(weekday, time_, team_h, goals_h, goals_a, team_a)

        embed = discord.Embed(title=Lang.lang(self, 'soccer_title', league))
        running_msg = "\n".join(match_msg(m) for m in running)
        if running_msg:
            embed.description = "\n".join(match_msg(m) for m in running)
        if allmatches or not running_msg:
            finished_msg = "\n".join(match_msg(m) for m in finished)
            upcoming_msg = "\n".join(match_msg(m) for m in upcoming)
            if finished_msg:
                embed.add_field(name=Lang.lang(self, 'match_finished'), value=finished_msg, inline=False)
            if upcoming_msg:
                embed.add_field(name=Lang.lang(self, 'match_upcoming'), value=upcoming_msg, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="buli")
    async def cmd_buli_livescores(self, ctx, allmatches=None):
        await ctx.invoke(self.bot.get_command('fußball'), 'ger.1', 'espn', allmatches)

    @commands.command(name="buli2")
    async def cmd_buli2_livescores(self, ctx, allmatches=None):
        await ctx.invoke(self.bot.get_command('fußball'), 'ger.2', 'espn', allmatches)

    @commands.command(name="table", alias="tabelle")
    async def cmd_table(self, ctx, league: str, raw_source: str = "espn"):
        try:
            league_name, tables = await self.bot.liveticker.get_standings(league, LTSource(raw_source))
        except ValueError:
            await add_reaction(ctx.message, Lang.CMDERROR)
        else:
            embed = discord.Embed(title=Lang.lang(self, 'table_title', league_name))
            for group_name, table in tables.items():
                table.sort(key=lambda x: x.rank)
                tables[group_name] = [x.display() for x in table]
            if len(tables) == 1:
                table = list(tables.values())[0]
                if len(table) > 10:
                    embed.add_field(name=Lang.lang(self, 'table_top'), value="\n".join(table[:len(table) // 2]))
                    embed.add_field(name=Lang.lang(self, 'table_bottom'), value="\n".join(table[len(table) // 2:]))
                else:
                    embed.description = "\n".join(table)
            else:
                for group_name, table in tables.items():
                    embed.add_field(name=group_name, value="\n".join(table))
            await ctx.send(embed=embed)

    @commands.command(name="bulitable")
    async def cmd_buli_table(self, ctx):
        await ctx.invoke(self.bot.get_command('table'), 'ger.1', 'espn')

    @commands.command(name="matches")
    async def cmd_matches_24h(self, ctx):
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
