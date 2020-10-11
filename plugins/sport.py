from datetime import datetime

import discord
from discord.ext import commands

from base import BasePlugin
from botutils import restclient
from conf import Lang


class Plugin(BasePlugin, name="Sport"):
    """Commands related to soccer or other sports"""

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)
        self.can_reload = True

    def default_config(self):
        return {
            'leagues': ["bl1", "bl2", "bl3", "uefanl"]
        }

    def default_storage(self):
        return []

    def command_help_string(self, command):
        return Lang.lang(self, "help_{}".format("_".join(command.qualified_name.split())))

    def command_description(self, command):
        name = "_".join(command.qualified_name.split())
        lang_name = "description_{}".format(name)
        result = Lang.lang(self, lang_name)
        return result if result != lang_name else Lang.lang(self, "help_{}".format(name))

    @commands.command(name="buli")
    async def buli_livestaende(self, ctx, allmatches=None):
        matches = restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/bl3")
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
            team_h = m.get('Team1', {}).get('TeamName')
            team_a = m.get('Team2', {}).get('TeamName')
            goals = m.get('Goals', [])
            goals_h = max(0, *(x.get('ScoreTeam1', 0) for x in goals)) if len(goals) else ("–" if m in upcoming else 0)
            goals_a = max(0, *(x.get('ScoreTeam2', 0) for x in goals)) if len(goals) else ("–" if m in upcoming else 0)
            return "{} [{}:{}] {}".format(team_h, goals_h, goals_a, team_a)

        embed = discord.Embed(title=Lang.lang(self, 'buli_title'))
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
