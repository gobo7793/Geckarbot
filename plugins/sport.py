from datetime import datetime

import discord
from discord.ext import commands

from base import BasePlugin
from botutils import restclient


class Plugin(BasePlugin, name="Sport"):
    """Commands related to soccer or other sports"""

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)
        self.can_reload = True

    def default_config(self):
        return {}

    def default_storage(self):
        return []

    @commands.command(name="buli")
    async def buli_livestaende(self, ctx, allmatches=None):
        matches = restclient.Client("https://www.openligadb.de/api").make_request("/getmatchdata/bl1")
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
            goals_h = max(0, *(x.get('ScoreTeam1', 0) for x in goals)) if len(goals) else 0
            goals_a = max(0, *(x.get('ScoreTeam2', 0) for x in goals)) if len(goals) else 0
            return "{} [{}:{}] {}".format(team_h, goals_h, goals_a, team_a)

        embed = discord.Embed(title="Bundesliga - Live")
        embed.description = "\n".join(match_msg(m) for m in running)
        if allmatches == "all":
            embed.add_field(name="Beendet", value="\n".join(match_msg(m) for m in finished), inline=False)
            embed.add_field(name="Bevorstehend", value="\n".join(match_msg(m) for m in upcoming), inline=False)
        await ctx.send(embed=embed)
