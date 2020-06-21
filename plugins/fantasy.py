import discord

from datetime import datetime
from discord.ext import commands
from conf import Config
from botutils import utils, permChecks
from botutils.enums import FantasyState
from Geckarbot import BasePlugin


class Plugin(BasePlugin, name="NFL Fantasyliga"):
    """Commands for the Fantasy game"""

    fantasymaster_role_id = 0

    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot)
        bot.register(self)

    def default_config(self):
        return {
            'league_link_a': "https://fantasy.espn.com/football/league/standings?leagueId=60409564",
            'league_link_b': "https://fantasy.espn.com/football/league/standings?leagueId=60409564",
            'commish_id_a': None,
            'commish_id_b': None, 
            'state': FantasyState.NA,
            'state_end': datetime.now(),
            'status': None
        }

    def fantasy_conf(self):
        return Config().get(self)

    def fantasy_lang(self, str_name, *args):
        return Config().lang(self, str_name, *args)


    @commands.group(name="fantasy", help="Get and manage informations about the NFL Fantasy Game",
                    description="Get the informations about the Fantasy Game or manage it. "
                                "Command only works in nfl-fantasy channel."
                                "Managing informations is only permitted for fantasymasters.")
    @permChecks.in_channel(Config().CHAN_IDS.get('nfl-fantasy', 0))
    async def fantasy(self, ctx):
        """Fantasy base command, return info command if no subcommand given"""
        if ctx.invoked_subcommand is None:
            await self.fantasy_info(ctx)

    @fantasy.command(name="ligen", help="Get the link to the Fantasy Leagues")
    async def fantasy_leagues(self, ctx):
        """Returns the Fantasy leagues"""
        links = self.fantasy_lang('league_links'), self.fantasy_conf()['league_link_a'], self.fantasy_conf()['league_link_b']

        await ctx.send(links)

    @fantasy.command(name="status", help="Get the current informations about the current fantasy state")
    async def fantasy_status(self, ctx):
        """Returns the Fantasy status message"""
        if self.fantasy_conf()['status']:
            status_msg = self.fantasy_lang('status_base', self.fantasy_conf()['status'])
        else:
            status_msg = self.fantasy_lang('status_base', self.fantasy_lang('status_none'))

        await ctx.send(status_msg)


    @fantasy.command(name="info", help="Get informations about the NFL Fantasy Game")
    async def fantasy_info(self, ctx):
        """Returns basic infos about the Fantasy game"""
        
        dateOutStr = self.fantasy_lang('info_date_str', self.fantasy_conf()['state_end'].strftime('%d.%m.%Y, %H:%M'))
        if not self.fantasy_conf()['commish_id_a']:
            await ctx.send(self.fantasy_lang('must_set_commish'))
        else:
            SuperCommish = discord.utils.get(ctx.guild.members, id=self.fantasy_conf()['supercommish_id']).mention
            CommishA = discord.utils.get(ctx.guild.members, id=self.fantasy_conf()['commish_id_a']).mention
            CommishB = discord.utils.get(ctx.guild.members, id=self.fantasy_conf()['commish_id_b']).mention

        if self.fantasy_conf()['state'] == FantasyState.Sign_up:
            if self.fantasy_conf()['state_end'] > datetime.now():
                dateOutStr = self.fantasy_lang('info_date_str', self.fantasy_conf()['state_end'].strftime('%d.%m.%Y'))
            else:
                dateOutStr = ""

            embed = discord.Embed(title=self.fantasy_lang('signup_phase_info', dateOutStr))
            embed.add_field(name=self.fantasy_lang('supercommish'), value=SuperCommish)
            embed.add_field(name=self.fantasy_lang('sign_up'), value=SuperCommish)
            
            if self.fantasy_conf()['status']:
                embed.description = self.fantasy_conf()['status']
            await ctx.send(embed=embed)

        elif self.fantasy_conf()['state'] == FantasyState.Predraft:
            embed = discord.Embed(title=self.fantasy_lang('predraft_phase_info', dateOutStr))
            
            embed.add_field(name=self.fantasy_lang('commish_a'), value=CommishA)
            embed.add_field(name=self.fantasy_lang('commish_b'), value=CommishB)
            embed.add_field(name=self.fantasy_lang('player_database'), value=self.fantasy_conf()['datalink'], inline=False)
            
            if self.fantasy_conf()['status']:
                embed.description = self.fantasy_conf()['status']
            await ctx.send(embed=embed)

        elif self.fantasy_conf()['state'] == FantasyState.Preseason:
            embed = discord.Embed(title=self.fantasy_lang('preseason_phase_info', dateOutStr))
            embed.add_field(name=self.fantasy_lang('commish_a'), value=CommishA)
            embed.add_field(name=self.fantasy_lang('commish_b'), value=CommishB)
            embed.add_field(name=self.fantasy_lang('league_a'), value=self.fantasy_conf()['league_link_a'], inline=False)
            embed.add_field(name=self.fantasy_lang('league_b'), value=self.fantasy_conf()['league_link_b'], inline=True)
            
            
            if self.fantasy_conf()['status']:
                embed.description = self.fantasy_conf()['status']
            await ctx.send(embed=embed)

        elif self.fantasy_conf()['state'] == FantasyState.Regular:
            embed = discord.Embed(title=self.fantasy_lang('regular_phase_info', dateOutStr))
            embed.add_field(name=self.fantasy_lang('commish_a'), value=CommishA)
            embed.add_field(name=self.fantasy_lang('commish_b'), value=CommishB)
            embed.add_field(name=self.fantasy_lang('league_a'), value=self.fantasy_conf()['league_link_a'], inline=False)
            embed.add_field(name=self.fantasy_lang('league_b'), value=self.fantasy_conf()['league_link_b'])
            
            if self.fantasy_conf()['status']:
                embed.description = self.fantasy_conf()['status']
            await ctx.send(embed=embed)

        elif self.fantasy_conf()['state'] == FantasyState.Postseason:
            embed = discord.Embed(title=self.fantasy_lang('postseason_phase_info', dateOutStr))
            embed.add_field(name=self.fantasy_lang('commish_a'), value=CommishA)
            embed.add_field(name=self.fantasy_lang('commish_b'), value=CommishB)
            embed.add_field(name=self.fantasy_lang('league_a'), value=self.fantasy_conf()['league_link_a'], inline=False)
            embed.add_field(name=self.fantasy_lang('league_b'), value=self.fantasy_conf()['league_link_b'])

            if self.fantasy_conf()['status']:
                embed.description = self.fantasy_conf()['status']
            await ctx.send(embed=embed)

        else:
            await ctx.send(self.fantasy_lang('config_error_reset'))
            embed = discord.Embed(title=self.fantasy_lang('config_error'))
            embed.add_field(name="Host ID", value=str(self.fantasy_conf()['supercommish_id']))
            embed.add_field(name="Host Nick", value=SuperCommish)
            embed.add_field(name="State", value=str(self.fantasy_conf()['state']))
            embed.add_field(name="Commish A", value=CommishA)
            embed.add_field(name="ID Commish A", value=(self.fantasy_conf()['commish_id_a']))
            embed.add_field(name="Commish B", value=CommishB)
            embed.add_field(name="ID Commish B", value=(self.fantasy_conf()['commish_id_b']))
            embed.add_field(name="State End", value=str(self.fantasy_conf()['state_end']))
            embed.add_field(name="Status", value=str(self.fantasy_conf()['status']))
            embed.add_field(name="Database Link", value=str(self.fantasy_conf()['datalink']))
            embed.add_field(name="League Link A", value=str(self.fantasy_conf()['league_link_a']))
            embed.add_field(name="League Link B", value=str(self.fantasy_conf()['league_link_b']))
            await utils.write_debug_channel(self.bot, embed)

    @fantasy.group(name="set", help="Set data about the fantasy game.", usage="<orga|comma|commb|linka|linkb|state|stateend|datalink|status")
    @commands.has_any_role(Config().ADMIN_ROLE_ID, Config().BOTMASTER_ROLE_ID, Config().ROLE_IDS.get('fantasymaster', 0))
    async def fantasy_set(self, ctx):
        """Basic set subcommand, does nothing"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.fantasy_set)

    @fantasy_set.command(name="datalink", help="Sets the link for the ESPN Players Database!", usage="<link>")
    async def fantasy_set_datalink(self, ctx, link):
        link = utils.clear_link(link)
        self.fantasy_conf()['datalink'] = link
        Config().save(self)
        await ctx.send(self.fantasy_lang('datalink_set'))

    @fantasy_set.command(name="linka", help="Sets the link for the Tipp-Liga A!", usage="<link>")
    async def fantasy_set_linka(self, ctx, link):
        link = utils.clear_link(link)
        self.fantasy_conf()['league_link_a'] = link
        Config().save(self)
        await ctx.send(self.fantasy_lang('linka_set'))

    @fantasy_set.command(name="linkb", help="Sets the link for the Tipp-Liga B!", usage="<link>")
    async def fantasy_set_linkb(self, ctx, link):
        link = utils.clear_link(link)
        self.fantasy_conf()['league_link_b'] = link
        Config().save(self)
        await ctx.send(self.fantasy_lang('linkb_set'))

    @fantasy_set.command(name="orga", help="Sets the Fantasy Organisator", usage="<user>")
    async def fantasy_set_host(self, ctx, user: discord.Member):
        """Sets the Fantasy Organisator"""
        
        self.fantasy_conf()['supercommish_id'] = user.id
        Config().save(self)
        await ctx.send(self.fantasy_lang('new_supercommish_set'))

    async def fantasy_save_state(self, ctx, new_state: FantasyState):
        """Saves the new Fantasy state and prints it to user"""
        self.fantasy_conf()['state'] = new_state
        state_str = str(FantasyState(self.fantasy_conf()['state']))
        state_str = state_str[state_str.find(".") + 1:].replace("_", " ")
        Config().save(self)
        await ctx.send(self.fantasy_lang('phase_set', state_str))
        
    @fantasy_set.command(name="state", help="Sets the Fantasy state (Sign_Up, Predraft, Preseason, Regular, Postseason)",
                     usage="<sign_up|predraft|preseason|regular|postseason>")
    async def fantasy_set_state(self, ctx, state):
        """Sets the current state of the fantasy Season. (Signup phase, Pre-Draft, Preseason, Regular Season, Postseason))"""
        if state.lower() == "sign_up":
            await self.fantasy_save_state(ctx, FantasyState.Sign_up)
        elif state.lower() == "predraft":
            await self.fantasy_save_state(ctx, FantasyState.Predraft)
        elif state.lower() == "preseason":
            await self.fantasy_save_state(ctx, FantasyState.Preseason)
        elif state.lower() == "regular":
            await self.fantasy_save_state(ctx, FantasyState.Regular)
        elif state.lower() == "postseason":
            await self.fantasy_save_state(ctx, FantasyState.Postseason)
        else:
            await ctx.send(self.fantasy_lang('invalid_phase'))

    @fantasy_set.command(name="comma", help="Sets the Commissioner of League A", usage="<user>")
    async def dsc_set_comm_a(self, ctx, user: discord.Member):
        """Sets the Commissioner for League A"""
        self.fantasy_conf()['commish_id_a'] = user.id
        Config().save(self)
        await ctx.send(self.fantasy_lang('new_commish_a_set'))
        
    @fantasy_set.command(name="commb", help="Sets the Commissioner of League B", usage="<user>")
    async def dsc_set_comm_b(self, ctx, user: discord.Member):
        """Sets the Commissioner for League B"""
        self.fantasy_conf()['commish_id_b'] = user.id
        Config().save(self)
        await ctx.send(self.fantasy_lang('new_commish_b_set'))

    @fantasy_set.command(name="stateend", help="Sets the state end date", usage="DD.MM.YYYY [HH:MM]",
                     description="Sets the end date and time for all the phases. "
                                 "If no time is given, 23:59 will be used.")
    async def fantasy_set_state_end(self, ctx, dateStr, timeStr=None):
        """Sets the end date (and time) of the current Fantasy state"""
        if not timeStr:
            timeStr = "23:59"
        self.fantasy_conf()['state_end'] = datetime.strptime(f"{dateStr} {timeStr}","%d.%m.%Y %H:%M")
        Config().save(self)
        await ctx.send(self.fantasy_lang('state_end_set'))

    @fantasy_set.command(name="status", help="Sets the status message", usage="[message]",
                     description="Sets a status message for additional informations. To remove give no message.")
    async def fantasy_set_status(self, ctx, *status_message):
        """Sets the dsc status message or removes it if no message is given"""
        self.fantasy_conf()['status'] = " ".join(status_message)
        Config().save(self)
        await ctx.send(self.fantasy_lang('status_set'))


