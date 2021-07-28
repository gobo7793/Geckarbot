import asyncio
import datetime
import logging
from enum import Enum
from typing import List, Generator, Tuple, Optional, Dict, Iterable

from base import BaseSubsystem, BasePlugin
from botutils import restclient
from botutils.converters import get_plugin_by_name
from data import Storage, Lang, Config
from subsystems import timers
from subsystems.timers import Job


class LTSource(Enum):
    """Data source"""
    OPENLIGADB = "oldb"
    ESPN = "espn"


class MatchStatus(Enum):
    """Current status of the match"""
    COMPLETED = ":ballot_box_with_check:"
    RUNNING = ":green_square:"
    UPCOMING = ":clock4:"
    POSTPONED = ":no_entry_sign:"
    UNKNOWN = "❔"

    @staticmethod
    def get(m: dict, src: LTSource):
        """
        Returns the current MatchStatus of the match

        :param m: raw match data
        :param src: data source
        :return: MatchStatus
        :rtype: MatchStatus
        :raises ValueError: if source is not valid
        """
        if src == LTSource.ESPN:
            status = m.get('status', {}).get('type', {}).get('state')
            if status == "pre":
                return MatchStatus.UPCOMING
            if status == "in":
                return MatchStatus.RUNNING
            if status == "post":
                if m.get('status', {}).get('type', {}).get('completed'):
                    return MatchStatus.COMPLETED
                return MatchStatus.POSTPONED
            return MatchStatus.UNKNOWN
        if src == LTSource.OPENLIGADB:
            if m.get('MatchIsFinished'):
                return MatchStatus.COMPLETED
            try:
                kickoff = datetime.datetime.strptime(m.get('MatchDateTimeUTC'), "%Y-%m-%dT%H:%M:%SZ") \
                    .replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
            except (ValueError, TypeError):
                return MatchStatus.UNKNOWN
            else:
                if kickoff < datetime.datetime.now():
                    return MatchStatus.RUNNING
                return MatchStatus.UPCOMING
        raise ValueError("Source {} is not supported.".format(src))


class TeamnameDict:
    """
    Set of name variants

    :param converter:
    :type converter: TeamnameConverter
    :param long_name: longest version of the teams name
    :param short_name: short distinct variant of the teams name
    :param abbr: abbreviation for the team (3-5 letters)
    :param emoji: logo of the team or other emoji that should be displayed
    :param other: additional variants of the teams name
    """

    def __init__(self, converter, long_name: str, short_name: str = None, abbr: str = None, emoji: str = None,
                 other: list = None):
        if short_name is None:
            short_name = long_name[:15]
        if abbr is None:
            abbr = short_name[:5].upper()
        if emoji is None:
            try:
                emoji = Lang.EMOJI['lettermap'][ord(abbr[0].lower()) - 97]
            except (IndexError, TypeError):
                emoji = "🏳️"
        if other is None:
            other = []
        self._converter = converter
        self.long_name = long_name
        self.short_name = short_name
        self.abbr = abbr
        self.emoji = emoji
        self.other = other

    def update(self, long_name: str = None, short_name: str = None, abbr: str = None, emoji: str = None):
        """Updates name variants or emoji of the TeamnameDict"""
        self._converter.update(self, long_name, short_name, abbr, emoji)

    def remove(self, other_str: str = None):
        """
        Removes an alternative or the whole TeamnameDict

        :param other_str: team name alternative
        """
        if other_str and other_str not in self:
            return
        if other_str and other_str in self.other:
            self._converter.remove_other(self, other_str)
        else:
            self._converter.remove(self)

    def add_other(self, other: str):
        """Adds an alternative name for the team"""
        if other not in self:
            self.other.append(other)

    def table_display(self) -> str:
        """Returns string prepared for display in the table"""
        if len(self.short_name) > 12:
            return f"{self.emoji} `{self.short_name[:11]}\u2026`"
        return "{} `{}{}`".format(self.emoji, self.short_name, " " * (11 - len(self.short_name)))

    def store(self, storage_path):
        """Saves this to the storage"""
        Storage().get(storage_path, container='teamname')[self.long_name] = self.to_dict()
        Storage().save(storage_path, container='teamname')

    def to_dict(self):
        return {'short': self.short_name, 'abbr': self.abbr, 'emoji': self.emoji, 'other': self.other}

    def __iter__(self):
        yield self.long_name
        yield self.short_name
        yield self.abbr
        for other in self.other:
            yield other


class TeamnameConverter:
    """
    Class for the conversion between team names

    :param liveticker: liveticker class
    """

    def __init__(self, liveticker):
        self.liveticker = liveticker
        self._teamnames = {}
        self._restore()

    def get(self, team: str, add_if_nonexist: bool = False) -> Optional[TeamnameDict]:
        """
        Returns the saved TeamnameDict for the given team name or adds a new entry if wanted

        :param team: name of the team
        :param add_if_nonexist: if the team name is unknown yet and this is true, a new entry will be added
        :return: associated TeamnameDict
        """
        teamnamedict = self._teamnames.get(team.lower())
        if teamnamedict is None and add_if_nonexist:
            return self.add(team)
        return teamnamedict

    def add(self, long_name: str, short_name: str = None, abbr: str = None, emoji: str = None,
            other: Iterable[str] = None) -> TeamnameDict:
        """
        Adds a new data set for a team to the converter.

        :param long_name: longest version of the teams name
        :param short_name: short distinct variant of the teams name
        :param abbr: abbreviation for the team (3-5 letters)
        :param emoji: logo of the team or other emoji that should be displayed
        :param other: additional variants of the teams name
        :return: Added TeamnameDict or existing TeamnameDict the name variants were added to
        :raises ValueError: if long and short name already exists but to different teams
        """
        if short_name is None:
            short_name = long_name[:15]
        if abbr is None:
            abbr = short_name[:5].upper()
        if emoji is None:
            try:
                emoji = Lang.EMOJI['lettermap'][ord(abbr[0].lower()) - 97]
            except (IndexError, TypeError):
                emoji = "🏳️"
        if other is None:
            other = []
        existing_long = self.get(long_name)
        existing_short = self.get(short_name)
        if existing_long and existing_short and existing_long != existing_short:
            raise ValueError("Long and short names already known and connected to different teams.")
        if existing_long:
            if long_name in existing_long.other:
                existing_long.other.remove(long_name)
            else:
                # Append to existing long
                for name in (short_name, abbr, *other):
                    if name.lower() not in self._teamnames:
                        existing_long.add_other(name)
                        self._teamnames[name.lower()] = existing_long
                existing_long.store(self.liveticker)
                return existing_long
        if existing_short:
            if short_name in existing_short.other:
                existing_short.other.remove(short_name)
            else:
                # Append to existing short
                for name in (long_name, abbr, *other):
                    if name.lower() not in self._teamnames:
                        existing_short.add_other(name)
                        self._teamnames[name.lower()] = existing_short
                existing_short.store(self.liveticker)
                return existing_short
        # Add new
        teamnamedict = TeamnameDict(self, long_name, short_name, abbr, emoji, other)
        self._teamnames[long_name.lower()] = teamnamedict
        self._teamnames[short_name.lower()] = teamnamedict
        for name in (abbr, *other):
            self._teamnames.setdefault(name.lower(), teamnamedict)
        teamnamedict.store(self.liveticker)
        return teamnamedict

    def remove(self, teamnamedict: TeamnameDict):
        """Removes a team from the converter"""
        for name in teamnamedict:
            if self.get(name) == teamnamedict:
                self._teamnames.pop(name.lower())
        Storage().get(self.liveticker, container='teamname').pop(teamnamedict.long_name)
        Storage().save(self.liveticker, container='teamname')

    def remove_other(self, teamnamedict: TeamnameDict, name: str):
        """Removes an alternative from the team"""
        if name in teamnamedict.other:
            teamnamedict.other.remove(name)
            if name.lower() in self._teamnames:
                self._teamnames.pop(name.lower())
            teamnamedict.store(self.liveticker)

    def update(self, teamnamedict: TeamnameDict, long_name: str = None, short_name: str = None, abbr: str = None,
               emoji: str = None) -> bool:
        """
        Updates name variants or emoji of the TeamnameDict

        :param teamnamedict: TeamnameDict to update
        :param long_name: new long name
        :param short_name: new short name
        :param abbr: new abbreviation
        :param emoji: new emoji
        :return: succession
        """
        other = teamnamedict.other
        teamnamedict.remove()
        if long_name:
            other.append(teamnamedict.long_name)
        if short_name:
            other.append(teamnamedict.short_name)
        try:
            self.add(long_name=long_name if long_name else teamnamedict.long_name,
                     short_name=short_name if short_name else teamnamedict.short_name,
                     abbr=abbr if abbr else teamnamedict.abbr,
                     emoji=emoji if emoji else teamnamedict.emoji,
                     other=other)
        except ValueError:
            # Update failed, reenter teamnamedict
            for name in teamnamedict:
                if not self.get(name):
                    self._teamnames[name.lower()] = teamnamedict
            teamnamedict.store(self.liveticker)
            return False
        return True

    def _restore(self):
        data = Storage().get(self.liveticker, container='teamname')
        for long_name, entry in data.items():
            try:
                self.add(long_name=str(long_name), short_name=str(entry['short']), abbr=str(entry['abbr']),
                         emoji=str(entry['emoji']), other=[str(x) for x in entry['other']])
            except ValueError:
                continue


class TableEntry:
    """
    Single entry of a table for the current standings in a league.

    :param data: raw data
    :param source: data source
    :param converter: Teamname converter
    """

    def __init__(self, data: dict, source: LTSource, converter: TeamnameConverter):
        self.source = source
        if source == LTSource.OPENLIGADB:
            self.rank = data['rank']
            self.team = converter.get(data['TeamName'])
            if not self.team:
                self.team = converter.add(long_name=data['TeamName'], short_name=data['ShortName'])
            self.won = data['Won']
            self.draw = data['Draw']
            self.lost = data['Lost']
            self.goals = data['Goals']
            self.goals_against = data['OpponentGoals']
            self.points = data['Points']
            self.rank_change = None
        elif source == LTSource.ESPN:
            stats = {x['name']: (int(x['value']) if x.get('value') is not None else None) for x in data['stats']}
            self.rank = stats.get('rank')
            self.team = converter.get(data['team']['displayName'])
            if not self.team:
                self.team = converter.add(long_name=data['team']['displayName'],
                                          short_name=data['team']['shortDisplayName'],
                                          abbr=data['team']['abbreviation'])
            self.won = stats.get('wins')
            self.draw = stats.get('ties')
            self.lost = stats.get('losses')
            self.goals = stats.get('pointsFor')
            self.goals_against = stats.get('pointsAgainst')
            self.points = stats.get('points')
            self.rank_change = stats.get('rankChange')
        else:
            raise ValueError('Invalid source')

    def display(self) -> str:
        """Returns the display string for use in an embed"""
        if len(self.team.short_name) > 12:
            team_str = f"{self.team.emoji} `{self.team.short_name[:11]}\u2026"
        else:
            team_str = f"{self.team.emoji} `{self.team.short_name:<12}"
        goal_diff = self.goals - self.goals_against
        sign = ["-", "±", "+"][(goal_diff > 0) - (goal_diff < 0) + 1]
        return f"`{self.rank:2} `{team_str}|" \
               f"{self.goals:2}:{self.goals_against:<2} ({sign}{abs(goal_diff):2})| {self.points:2}`"


class MatchStub:
    """
    Match with minimal info (used for stored kickoffs)

    :param kickoff: kickoff datetime
    :param home_team: name of the home team
    :param away_team: name of the away team
    :param home_team_id: id of the home team
    :param away_team_id: id of the away team
    """

    def __init__(self, kickoff: datetime.datetime, home_team: str, away_team: str, home_team_id: str,
                 away_team_id: str):
        self.kickoff = kickoff
        self.home_team = Config().bot.liveticker.teamname_converter.get(home_team, add_if_nonexist=True)
        self.away_team = Config().bot.liveticker.teamname_converter.get(away_team, add_if_nonexist=True)
        self.home_team_id = home_team_id
        self.away_team_id = away_team_id

    @classmethod
    def from_storage(cls, time_kickoff: datetime.datetime, m: dict):
        """Returns a MatchStub formed from the stored data"""
        team_names = list(m.values())
        team_ids = list(m.keys())
        return cls(kickoff=time_kickoff, home_team=team_names[0], home_team_id=team_ids[0], away_team=team_names[1],
                   away_team_id=team_ids[1])

    def to_storage(self):
        """Transforms the data for the storage"""
        return {self.home_team_id: self.home_team.long_name, self.away_team_id: self.away_team.long_name}


class Match(MatchStub):
    """
    Soccer match

    :param match_id: id of the match
    :param kickoff: kickoff datetime
    :param minute: current minute
    :param home_team: name of the home team
    :param away_team: name of the away team
    :param home_team_id: id of the home team
    :param away_team_id: id of the away team
    :param status: current status of the game
    :param raw_events: list of all events
    :param venue: (stadium, city) of the match
    :param score: current score
    :param new_events: list of new events in comparison to the last execution
    :param matchday: current matchday
    """

    def __init__(self, match_id: str, kickoff: datetime.datetime, minute: str, home_team: str, home_team_id: str,
                 away_team: str, away_team_id: str, status: MatchStatus, raw_events: list, venue: Tuple[str, str],
                 score: dict = None, new_events: list = None, matchday: int = None):
        super().__init__(kickoff=kickoff, home_team=home_team, away_team=away_team, home_team_id=home_team_id,
                         away_team_id=away_team_id)
        if new_events is None:
            new_events = []
        self.match_id = match_id
        self.minute = minute
        self.status = status
        self.raw_events = raw_events
        self.new_events = new_events
        self.matchday = matchday
        self.venue = venue
        if score:
            self.score = score
        else:
            self.score = {self.home_team_id: 0, self.away_team_id: 0}

    @classmethod
    def from_openligadb(cls, m: dict, new_events: list = None):
        """
        Match by a OpenLigaDB source

        :param m: match data
        :param new_events: list of new events
        :return: Match object
        :rtype: Match
        """
        # Extract kickoff into datetime object
        if new_events is None:
            new_events = []
        try:
            kickoff = datetime.datetime.strptime(m.get('MatchDateTimeUTC'), "%Y-%m-%dT%H:%M:%SZ") \
                .replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
        except (ValueError, TypeError):
            kickoff = None
        # Calculate current minute
        if kickoff:
            minute = (datetime.datetime.now() - kickoff).seconds // 60
            if minute > 45:
                minute = max(45, minute - 15)
        else:
            minute = None
        # Note team IDs
        home_id = m.get('Team1', {}).get('TeamId')
        away_id = m.get('Team2', {}).get('TeamId')

        match = cls(match_id=m.get('MatchID'),
                    kickoff=kickoff,
                    minute=str(minute),
                    home_team=m.get('Team1', {}).get('TeamName'),
                    home_team_id=home_id,
                    away_team=m.get('Team2', {}).get('TeamName'),
                    away_team_id=away_id,
                    score={home_id: max(0, 0, *(g.get('ScoreTeam1', 0) for g in m.get('Goals', []))),
                           away_id: max(0, 0, *(g.get('ScoreTeam2', 0) for g in m.get('Goals', [])))},
                    raw_events=m.get('Goals'),
                    venue=(m.get('Location', {}).get('LocationStadium'), m.get('Location', {}).get('LocationCity')),
                    status=MatchStatus.get(m, LTSource.OPENLIGADB),
                    new_events=new_events,
                    matchday=m.get('Group', {}).get('GroupOrderID'))
        return match

    @classmethod
    def from_espn(cls, m: dict, new_events: list = None):
        """
        Match by a ESPN source

        :param m: match data
        :param new_events: list of new events
        :return: Match object
        :rtype: Match
        """
        # Extract kickoff into datetime object
        try:
            kickoff = datetime.datetime.strptime(m.get('date'), "%Y-%m-%dT%H:%MZ") \
                .replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
        except (ValueError, TypeError):
            kickoff = None
        # Get home and away team
        home_team, away_team, home_id, away_id, home_score, away_score = None, None, None, None, None, None
        competition = m.get('competitions', [{}])[0]
        for team in competition.get('competitors'):
            if team.get('homeAway') == "home":
                home_team = team.get('team', {}).get('displayName')
                home_id = team.get('id')
                home_score = team.get('score')
            elif team.get('homeAway') == "away":
                away_team = team.get('team', {}).get('displayName')
                away_id = team.get('id')
                away_score = team.get('score')

        # Put all informations together
        match = cls(match_id=m.get('uid'),
                    kickoff=kickoff,
                    minute=m.get('status', {}).get('displayClock'),
                    home_team=home_team,
                    home_team_id=home_id,
                    away_team=away_team,
                    away_team_id=away_id,
                    score={home_id: home_score, away_id: away_score},
                    new_events=new_events,
                    raw_events=m.get('competitions', [{}])[0].get('details'),
                    venue=(competition.get('venue', {}).get('fullName'),
                           competition.get('venue', {}).get('address', {}).get('city')),
                    status=MatchStatus.get(m, LTSource.ESPN))
        return match


class PlayerEvent:
    """Event during a match"""

    def __init__(self, event_id: str, player: str, minute: str):
        self.event_id = event_id
        self.player = player
        self.minute = minute

    def display(self) -> str:
        """Returns display string"""
        return "<PlayerEvent {} ({})>".format(self.player, self.minute)


class Goal(PlayerEvent):
    """
    PlayerEvent for a goal
    :param event_id: id of the goal
    :param player: goalgetter
    :param minute: match minute the goal was scored
    :param score: score of the match at the time of the goal
    :param is_owngoal: whether goal was scored by the defending team
    :param is_penalty: whether goal was scored as a penalty
    """

    def __init__(self, event_id, player, minute, score: dict, is_owngoal: bool, is_penalty: bool):
        super().__init__(event_id, player, minute)
        self.score = score
        self.is_owngoal = is_owngoal
        self.is_penalty = is_penalty
        self.is_overtime = False

    @classmethod
    def from_openligadb(cls, g: dict, home_id: str, away_id: str):
        """
        Builds the Goal object from a OpenLigaDB source

        :param g: goal data
        :param home_id: id of the home team
        :param away_id: id of the away team
        :return: Goal object
        :rtype: Goal
        """
        goal = cls(event_id=g.get('GoalID'),
                   player=g.get('GoalGetterName'),
                   minute=g.get('MatchMinute'),
                   score={home_id: g.get('ScoreTeam1'),
                          away_id: g.get('ScoreTeam2')},
                   is_owngoal=g.get('IsOwnGoal'),
                   is_penalty=g.get('IsPenalty'))
        goal.is_overtime = g.get('IsOvertime')
        return goal

    @classmethod
    def from_espn(cls, g: dict, score: dict):
        """
        Builds the Goal object from a ESPN source

        :param g: goal data
        :param score: current score
        :return: Goal object
        :rtype: Goal
        """
        score[g.get('team', {}).get('id')] += g.get('scoreValue')
        goal = cls(event_id="{}/{}/{}".format(g.get('type', {}).get('id'),
                                              g.get('clock', {}).get('value'),
                                              g.get('athletesInvolved', [{}])[0].get('id')),
                   player=g.get('athletesInvolved', [{}])[0].get('displayName'),
                   minute=g.get('clock', {}).get('displayValue'),
                   score=score,
                   is_owngoal=g.get('ownGoal'),
                   is_penalty=g.get('penaltyKick'))
        return goal

    def display(self):
        if self.is_owngoal:
            return ":soccer::back: {}:{} {} ({})".format(*list(self.score.values())[0:2], self.player, self.minute)
        if self.is_penalty:
            return ":soccer::goal: {}:{} {} ({})".format(*list(self.score.values())[0:2], self.player, self.minute)
        return ":soccer: {}:{} {} ({})".format(*list(self.score.values())[0:2], self.player, self.minute)


class YellowCard(PlayerEvent):
    """PlayerEvent for a yellow card"""

    @classmethod
    def from_espn(cls, yc: dict):
        """
        PlayerEvent for a yellow card from a ESPN source

        :param yc: event data
        :return: YellowCard
        :rtype: YellowCard
        """
        return cls(event_id="{}/{}/{}".format(yc.get('type', {}).get('id'),
                                              yc.get('clock', {}).get('value'),
                                              yc.get('athletesInvolved', [{}])[0].get('id')),
                   player=yc.get('athletesInvolved', [{}])[0].get('displayName'),
                   minute=yc.get('clock', {}).get('displayValue'))

    def display(self):
        return ":yellow_square: {} ({})".format(self.player, self.minute)


class RedCard(PlayerEvent):
    """PlayerEvent for a red card"""

    @classmethod
    def from_espn(cls, rc: dict):
        """
        PlayerEvent for a red card from a ESPN source

        :param rc: event data
        :return: RedCard
        :rtype: RedCard
        """
        return cls(event_id="{}/{}/{}".format(rc.get('type', {}).get('id'),
                                              rc.get('clock', {}).get('value'),
                                              rc.get('athletesInvolved', [{}])[0].get('id')),
                   player=rc.get('athletesInvolved', [{}])[0].get('displayName'),
                   minute=rc.get('clock', {}).get('displayValue'))

    def display(self):
        return ":red_square: {} ({})".format(self.player, self.minute)


class PlayerEventEnum(Enum):
    """Enum for the different types of PlayerEvents"""
    GOAL = Goal
    YELLOWCARD = YellowCard
    REDCARD = RedCard

    @staticmethod
    def build_player_event(event: dict, score: dict) -> PlayerEvent:
        """
        Builds the corresponding PlayerEvent from the given event dict

        :param event: event data dictionary
        :param score: current score
        :return: Goal/RedCard/YellowCard
        :raises ValueError: when event type does not match with the expected values
        """
        if event.get('scoringPlay'):
            return Goal.from_espn(event, score)
        if event.get('type', {}).get('id') == "93":
            return RedCard.from_espn(event)
        if event.get('type', {}).get('id') == "94":
            return YellowCard.from_espn(event)
        raise ValueError("Unexpected event type {}: {}".format(event.get('type', {}).get('id'),
                                                               event.get('type', {}).get('name')))


class LivetickerEvent:
    def __init__(self, league, matches):
        self.league = league
        self.matches = matches


class LivetickerKickoff(LivetickerEvent):
    def __init__(self, league, matches, kickoff):
        super().__init__(league, matches)
        self.kickoff = kickoff


class LivetickerUpdate(LivetickerEvent):
    """
    LivetickerEvent for the mid-game update

    :param league: league of the Registration
    :param matches: current matches
    :param new_events: dictionary of the new events per match
    """

    def __init__(self, league: str, matches: list, new_events: dict):
        m_list = []
        for m in matches:
            m.new_events = new_events.get(m.match_id)
            m_list.append(m)
        super().__init__(league, m_list)


class LivetickerFinish(LivetickerEvent):
    pass


class CoroRegistration:
    """Registration for a single Coroutine. Liveticker updates for the specified league will be transmitted to the
    specified coro

    :param league_reg: Registration of the corresponding league
    :type league_reg: LeagueRegistration
    :param coro: Coroutine which receives the LivetickerEvents
    :param periodic: whether the registration should receive mid-game updates"""

    def __init__(self, league_reg, plugin, coro, interval: int, periodic: bool = False):
        self.league_reg = league_reg
        self.plugin_name = plugin.get_name()
        self.coro = coro
        self.periodic = periodic
        self.interval = interval
        self.last_events = {}
        self.logger = logging.getLogger(__name__)

    def deregister(self):
        self.league_reg.deregister_coro(self)

    def unload(self):
        self.league_reg.unload_coro(self)

    def next_kickoff(self):
        """Returns datetime of the next match"""
        return self.league_reg.next_kickoff()

    def next_execution(self):
        """Returns datetime of the next timer execution"""
        return self.league_reg.next_execution()

    async def update(self, job: Job):
        """
        Coroutine used by the interval timer during matches. Manufactures the LivetickerUpdate for the coro.
        """
        self.logger.debug("CoroReg updates.")
        matches = self.league_reg.extract_kickoffs_with_matches()[job.data['start']]
        new_events = {}
        for m in matches:
            if m.match_id not in self.last_events:
                self.last_events[m.match_id] = []
            events = []
            if self.league_reg.source == LTSource.OPENLIGADB:
                for g in m.raw_events:
                    goal = Goal.from_openligadb(g, m.home_team_id, m.away_team_id)
                    if goal.event_id not in self.last_events[m.match_id]:
                        events.append(goal)
            elif self.league_reg.source == LTSource.ESPN:
                tmp_score = {m.home_team_id: 0, m.away_team_id: 0}
                for e in m.raw_events:
                    event = PlayerEventEnum.build_player_event(e, tmp_score.copy())
                    if isinstance(event, Goal):
                        tmp_score = event.score
                    if event.event_id not in self.last_events[m.match_id]:
                        events.append(event)
            new_events[m.match_id] = events
            self.last_events[m.match_id].extend([e.event_id for e in events])
        await self.coro(LivetickerUpdate(self.league_reg.league, matches, new_events))

    async def update_kickoff(self, time_kickoff: datetime.datetime, matches: list):
        await self.coro(LivetickerKickoff(self.league_reg.league, matches, time_kickoff))

    async def update_finished(self, match_list):
        await self.coro(LivetickerFinish(self.league_reg.league, match_list))

    def storage(self):
        return {
            'plugin': self.plugin_name,
            'coro': self.coro.__name__,
            'periodic': self.periodic
        }

    def __eq__(self, other):
        return self.coro == other.coro and self.periodic == other.periodic

    def __str__(self):
        return "<liveticker.CoroRegistration; coro={}; periodic={}>" \
            .format(self.coro, self.periodic)

    def __bool__(self):
        return bool(self.next_execution())


class LeagueRegistration:
    """
    Registration for a league. Manages central data collection and scheduling of timers.

    :type listener: Liveticker
    :param listener: central Liveticker node
    :param league: league key
    :param source: data source
    """

    def __init__(self, listener, league: str, source: LTSource):
        self.listener = listener
        self.league = league
        self.source = source
        self.registrations = []
        self.logger = logging.getLogger(__name__)
        self.kickoffs = {}
        self.kickoff_timers = []
        self.intermediate_timers = []
        self.matches = []
        self.finished = []

    @classmethod
    async def create(cls, listener, league: str, source: LTSource):
        """New LeagueRegistration"""
        l_reg = LeagueRegistration(listener, league, source)
        await l_reg.schedule_kickoffs(until=listener.semiweekly_timer.next_execution())
        return l_reg

    @classmethod
    async def restore(cls, listener, league: str, source: LTSource):
        """Restored LeagueRegistration"""
        l_reg = LeagueRegistration(listener, league, source)
        kickoff_data = Storage().get(listener)['registrations'][source.value][league]['kickoffs']
        for raw_kickoff, matches in kickoff_data.items():
            time_kickoff = datetime.datetime.strptime(raw_kickoff, "%Y-%m-%d %H:%M")
            matches_ = [MatchStub.from_storage(time_kickoff, m) for m in matches]
            await l_reg.schedule_kickoff_single(time_kickoff, matches_)
        return l_reg

    async def register(self, plugin, coro, interval: int, periodic: bool):
        """Registers a CoroReg for this league"""
        reg = CoroRegistration(self, plugin, coro, interval, periodic)
        if reg not in self.registrations:
            self.registrations.append(reg)
            reg_storage = reg.storage()
            league_reg = Storage().get(self.listener)['registrations'][self.source.value][self.league]
            if reg_storage not in league_reg['coro_regs']:
                league_reg['coro_regs'].append(reg_storage)
                Storage().save(self.listener)
            for match_timer in self.intermediate_timers:
                await reg.update_kickoff(match_timer.data['start'], match_timer.data['matches'])
        return reg

    def deregister(self):
        """Deregisters this LeagueReg correctly"""
        for job in self.kickoff_timers:
            job.cancel()
        for job in self.intermediate_timers:
            job.cancel()
        self.listener.deregister(self)

    def unload(self):
        """Unloads this LeagueRegistration"""
        for job in self.kickoff_timers:
            job.cancel()
        for job in self.intermediate_timers:
            job.cancel()
        self.listener.unload(self)

    def deregister_coro(self, coro: CoroRegistration):
        """Finishes the deregistration of a CoroRegistration"""
        reg_storage = coro.storage()
        leag_reg = Storage().get(self.listener)['registrations'][self.source.value][self.league]
        if reg_storage in leag_reg['coro_regs']:
            leag_reg['coro_regs'].remove(reg_storage)
            Storage().save(self.listener)
        if coro in self.registrations:
            self.registrations.remove(coro)
        if not self.registrations:
            self.deregister()

    def unload_coro(self, coro: CoroRegistration):
        """Finishes the unloading of a CoroRegistration"""
        if coro in self.registrations:
            self.registrations.remove(coro)
        if not self.registrations:
            self.unload()

    async def update_matches(self, matchday=None):
        """Updates the matches and current standings of the league"""
        if self.source == LTSource.OPENLIGADB:
            if matchday:
                self.matches = await self.get_matches_oldb_by_matchday(matchday=matchday)
            else:
                self.matches = await self.get_matches_oldb_by_date()
        elif self.source == LTSource.ESPN:
            self.matches = await self.get_matches_espn()
        return self.matches

    async def get_matches_espn(self, from_day: datetime.date = None, until_day: datetime.date = None) -> List[Match]:
        """Requests espn match data for a specified date range"""
        if from_day is None:
            from_day = datetime.date.today()
        if until_day is None:
            until_day = from_day

        dates = "{}-{}".format(from_day.strftime("%Y%m%d"), until_day.strftime("%Y%m%d"))
        _ = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports") \
            .request(f"/soccer/{self.league}/scoreboard", params={'dates': dates})
        await asyncio.sleep(5)
        data = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports") \
            .request(f"/soccer/{self.league}/scoreboard", params={'dates': dates})
        matches = [Match.from_espn(x) for x in data['events']]
        return matches

    async def get_matches_oldb_by_date(self, from_day: datetime.date = None, until_day: datetime.date = None,
                                       limit: int = 5) -> List[Match]:
        """
        Requests openligadb match data for a specified date range. Doesn't support past days or dates too far into
        future since it is all matchday-based and starts from the present matchday.

        :param from_day: start of the date range. No past days supported.
        :param until_day: end of the date range.
        :param limit: maximum number of requests respectivly the number of matchdays checked for fitting matches.
        """
        if from_day is None:
            from_day = datetime.date.today()
        if until_day is None:
            until_day = from_day

        data = await restclient.Client("https://www.openligadb.de/api").request("/getmatchdata/{}".format(self.league))
        matches = []
        if not data:
            return []
        for m in data:
            match = Match.from_openligadb(m)
            if match.kickoff.date() > until_day:
                break
            if match.kickoff.date() >= from_day:
                matches.append(match)
        else:
            for i in range(1, limit):
                add_matches = await self.get_matches_oldb_by_matchday(matchday=matches[-1].matchday)
                if not add_matches:
                    break
                else:
                    matches.extend(add_matches)
        return matches

    async def get_matches_oldb_by_matchday(self, matchday: int, season: int = None):
        if season is None:
            date = datetime.date.today()
            season = date.year if date.month > 6 else date.year - 1
        data = await restclient.Client("https://www.openligadb.de/api").request(
            f"/getmatchdata/{self.league}/{season}/{matchday}")
        return [Match.from_openligadb(m) for m in data]

    def extract_kickoffs_with_matches(self) -> dict:
        """
        Groups the matches by their kickoff times

        :return: dict with the kickoff as the key and a list of matches as value
        """
        kickoff_dict = {}
        for match in self.matches:
            if match.status == MatchStatus.POSTPONED:
                continue
            if match.kickoff in kickoff_dict:  # Insert at kickoff
                kickoff_dict[match.kickoff].append(match)
            else:
                kickoff_dict[match.kickoff] = [match]
        return kickoff_dict

    def matchday(self):
        """Returns the current matchday (OLDB only)"""
        if self.source == LTSource.OPENLIGADB:
            for match in self.matches:
                md = match.matchday
                if md:
                    return md
        return None

    async def schedule_kickoffs(self, until: datetime.datetime):
        """
        Schedules timers for the kickoffs of the matches until the specified date

        :param until: datetime of the day before the next semi-weekly execution
        :raises ValueError: if source does not provide support scheduling of kickoffs
        """
        kickoffs = {}
        now = datetime.datetime.now()
        Storage().get(self.listener)['registrations'][self.source.value][self.league]['kickoffs'] = {}

        matches: List[Match]
        if self.source == LTSource.ESPN:
            # Match collection for ESPN
            matches = await self.get_matches_espn(from_day=now, until_day=until)
        elif self.source == LTSource.OPENLIGADB:
            # Match collection for OpenLigaDB
            matches = await self.get_matches_oldb_by_date(from_day=now, until_day=until)
        else:
            raise ValueError("Source {} is not supported.".format(self.source))

        for match in matches:
            # Group by kickoff
            if match.status in [MatchStatus.COMPLETED, MatchStatus.POSTPONED]:
                continue
            if match.kickoff not in kickoffs:
                kickoffs[match.kickoff] = []
            kickoffs[match.kickoff].append(match)

        for time_kickoff, matches_ in kickoffs.items():
            # Actual scheduling
            if time_kickoff > until:
                continue  # Kickoff not in this period
            await self.schedule_kickoff_single(time_kickoff, matches_)
            storage_kickoffs = Storage().get(self.listener)['registrations'][self.source.value][self.league]['kickoffs']
            storage_kickoffs[time_kickoff.strftime("%Y-%m-%d %H:%M")] = [m.to_storage() for m in matches_]
        Storage().save(self.listener)

    async def schedule_kickoff_single(self, time_kickoff: datetime.datetime, matches: list):
        """Schedules a single kickoff time."""
        now = datetime.datetime.now()
        self.logger.debug(time_kickoff)
        if time_kickoff > now:
            # Kickoff in the future
            kickoff_timer = self.listener.bot.timers.schedule(
                coro=self._schedule_match_timer,
                td=timers.timedict(year=time_kickoff.year, month=time_kickoff.month, monthday=time_kickoff.day,
                                   hour=time_kickoff.hour, minute=time_kickoff.minute),
                data={'start': time_kickoff, 'matches': matches})
            self.kickoff_timers.append(kickoff_timer)
        elif (now - time_kickoff) < datetime.timedelta(hours=2):
            # Kickoff in the past, match running
            await self._schedule_match_timer(kickoff=time_kickoff, matches=matches)
            for coro_reg in self.registrations:
                await coro_reg.update_kickoff(time_kickoff, matches)

    async def _schedule_match_timer(self, job: Job = None, kickoff: datetime.datetime = None, matches: list = None):
        """
        Schedules the timer for the match updates

        :param job: is used if this method is called by the timer
        :param kickoff: is used if the match is actually running
        :param matches: is used if the match is actually running
        """
        now = datetime.datetime.now().replace(second=0, microsecond=0)
        if job:
            kickoff = job.data['start']
            matches = job.data['matches']
            job.cancel()
        if not kickoff:
            return

        interval_set = set([c.interval for c in self.registrations])
        td = timers.timedict(minute=[(x + kickoff.minute) % 60 for x in range(0, 60) if 0 in
                                     (x % y for y in interval_set)])
        match_timer = self.listener.bot.timers.schedule(coro=self.update_periodic_coros, td=td,
                                                        data={'start': kickoff, 'matches': matches})
        self.intermediate_timers.append(match_timer)
        await self.update_kickoff_coros(match_timer)
        if match_timer.next_execution() <= now:
            match_timer.execute()

    def next_kickoff(self):
        """Returns datetime of the next match"""
        kickoffs = (i.next_execution() for i in self.kickoff_timers if i)
        if kickoffs:
            return min(kickoffs)
        return None

    def next_execution(self):
        """Returns datetime and type of the next timer execution"""
        kickoffs = [j for j in (i.next_execution() for i in self.kickoff_timers if i) if j]
        intermed = [j for j in (i.next_execution() for i in self.intermediate_timers if i) if j]
        if kickoffs and intermed:
            next_exec, timer_type = min((min(kickoffs), "kickoff"), (min(intermed), "intermediate"))
        elif kickoffs:
            next_exec, timer_type = min(kickoffs), "kickoff"
        elif intermed:
            next_exec, timer_type = min(intermed), "intermediate"
        else:
            return None
        return next_exec, timer_type

    async def update_kickoff_coros(self, job: Job):
        for coro_reg in self.registrations:
            await coro_reg.update_kickoff(job.data['start'], job.data['matches'])

    async def update_periodic_coros(self, job: Job):
        """
        Regularly updates coros and checks if matches are still running.

        :param job:
        :return:
        """
        if job.data['start'] == datetime.datetime.now().replace(second=0, microsecond=0):
            return
        new_finished = []
        await self.update_matches()
        matches = self.extract_kickoffs_with_matches()[job.data['start']]
        if job.data['start'] + datetime.timedelta(hours=3.5) < datetime.datetime.now():
            new_finished = matches
            self.finished.extend([m.match_id for m in matches])
        else:
            for match in matches:
                if match.status == MatchStatus.COMPLETED and match.match_id not in self.finished:
                    new_finished.append(match)
                    self.finished.append(match.match_id)
        for coro_reg in self.registrations:
            if coro_reg.periodic and \
                    (datetime.datetime.now() - job.data['start']).seconds % (coro_reg.interval * 60) == 0:
                await coro_reg.update(job)
            if new_finished:
                await coro_reg.update_finished(new_finished)
        if len([m for m in matches if m.match_id not in self.finished]) == 0:
            job.cancel()

    def __str__(self):
        next_exec = self.next_execution()
        if next_exec:
            next_exec = next_exec[0].strftime('%Y-%m-%d - %H:%M'), next_exec[1]
        return f"<liveticker.LeagueRegistration; league={self.league}; src={self.source.value}; " \
               f"regs={len(self.registrations)}; next={next_exec}>"

    def __bool__(self):
        return bool(self.next_execution())


class Liveticker(BaseSubsystem):
    """Subsystem for the registration and operation of sports livetickers"""

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.registrations = {x: {} for x in LTSource}
        self.teamname_converter = TeamnameConverter(self)
        self.restored = False
        self.hourly_timer = None
        self.semiweekly_timer = None

        # Update storage
        if not Storage().get(self).get('storage_version'):
            self.logger.debug("default storage set")
            regs = Storage().get(self)
            for src, l_regs in regs.items():
                for league, c_regs in l_regs.items():
                    regs[src][league] = {
                        'kickoffs': {},
                        'coro_regs': c_regs
                    }
            Storage().set(self, {'storage_version': 1, 'registrations': regs, 'next_semiweekly': None})
            Storage().save(self)

        # pylint: disable=unused-variable
        @bot.listen()
        async def on_ready():
            plugins = self.bot.get_normalplugins()
            await self.restore(plugins)
            self.restored = True
            self.hourly_timer = self.bot.timers.schedule(coro=self._hourly_timer_coro, td=timers.timedict(minute=[0]))
            self.semiweekly_timer = self.bot.timers.schedule(coro=self._semiweekly_timer_coro,
                                                             td=timers.timedict(weekday=[2, 5], hour=[4], minute=[0]))
            if Storage().get(self).get('next_semiweekly') is None or \
                    datetime.datetime.strptime(Storage().get(self)['next_semiweekly'], "%Y-%m-%d %H:%M") \
                    < datetime.datetime.now():
                self.semiweekly_timer.execute()

    def default_storage(self, container=None):
        if container == 'teamname':
            return {}
        storage = {
            'storage_version': 1,
            'registrations': {},
            'next_semiweekly': None
        }
        for src in LTSource.__members__.values():
            storage['registrations'][src.value] = {}
        return storage

    async def register(self, league: str, raw_source: str, plugin: BasePlugin,
                       coro, interval: int = 15, periodic: bool = True) -> CoroRegistration:
        """
        Registers a new liveticker for the specified league.

        :param interval: time between two intermediate updates
        :param raw_source: which data source should be used (espn, oldb etc.)
        :param plugin: plugin where all coroutines are in
        :param league: League the liveticker should observe
        :param coro: coroutine for the events
        :type coro: function
        :param periodic: if coro should be updated automatically
        :return: CoroRegistration
        """
        source = LTSource(raw_source)
        league_exists = league in Storage().get(self)['registrations'][source.value]
        if not league_exists:
            Storage().get(self)['registrations'][source.value][league] = {'kickoffs': {}, 'coro_regs': []}
            Storage().save(self)
        if league not in self.registrations[source]:
            if league_exists:
                self.registrations[source][league] = await LeagueRegistration.restore(self, league, source)
            else:
                self.registrations[source][league] = await LeagueRegistration.create(self, league, source)
        coro_reg = await self.registrations[source][league].register(plugin, coro, interval, periodic)
        return coro_reg

    def deregister(self, reg: LeagueRegistration):
        """
        Finishes the deregistration of a LeagueRegistration

        :param reg: LeagueRegistration
        """
        if reg.league in self.registrations[reg.source]:
            self.registrations[reg.source].pop(reg.league)
        if reg.league in Storage().get(self)['registrations'][reg.source.value]:
            Storage().get(self)['registrations'][reg.source.value].pop(reg.league)
            Storage().save(self)

    def unload(self, reg: LeagueRegistration):
        if reg.league in self.registrations[reg.source]:
            self.registrations[reg.source].pop(reg.league)

    def search_league(self, sources=None, leagues=None) -> Generator[LeagueRegistration, None, None]:
        """
        Searches all LeagueRegistrations fulfilling the requirements

        :param sources: list of sources
        :type sources: List[LTSource]
        :param leagues: list of league keys
        :type leagues: List[str]
        :return: LeagueRegistration
        """
        if sources is None:
            sources = []
        if leagues is None:
            leagues = []
        for src, l_regs in self.registrations.items():
            if sources and src not in sources:
                continue
            for league, l_reg in l_regs.items():
                l_reg: LeagueRegistration
                if leagues and league not in leagues:
                    continue
                yield l_reg

    def search_coro(self, plugins: list = None, sources: list = None, leagues: list = None) -> \
            Generator[Tuple[LTSource, str, CoroRegistration], None, None]:
        """
        Searches all CoroRegistrations fulfilling the requirements

        :param plugins: list of plugin names
        :type plugins: List[str]
        :param sources: list of sources
        :type sources: List[LTSource]
        :param leagues: list of league keys
        :type leagues: List[str]
        :return: source, league, coro-registration
        """
        if sources is None:
            sources = []
        if leagues is None:
            leagues = []
        if plugins is None:
            plugins = []
        l_reg: LeagueRegistration
        for l_reg in self.search_league(sources=sources, leagues=leagues):
            c_reg: CoroRegistration
            for c_reg in l_reg.registrations:
                if plugins and c_reg.plugin_name not in plugins:
                    continue
                yield l_reg.source, l_reg.league, c_reg

    async def restore(self, plugins: list):
        """
        Restores saved registrations from the storage

        :param plugins: List of all active plugins
        """
        i, j = 0, 0
        for src, registrations in Storage().get(self)['registrations'].items():
            for league in registrations:
                for c_reg in registrations[league]['coro_regs']:
                    if c_reg['plugin'] in plugins:
                        try:
                            coro = getattr(get_plugin_by_name(c_reg['plugin']),
                                           c_reg['coro']) if c_reg['coro'] else None
                        except AttributeError:
                            j += 1
                        else:
                            i += 1
                            await self.register(plugin=get_plugin_by_name(c_reg['plugin']),
                                                league=league,
                                                raw_source=src,
                                                coro=coro,
                                                periodic=c_reg['periodic'])
        self.logger.debug('%d Liveticker registrations restored. %d failed.', i, j)

    def unload_plugin(self, plugin_name: str):
        """
        Unloads all active registrations belonging to the specified plugin

        :param plugin_name: name of the plugin
        """
        for _, _, c_reg in self.search_coro(plugins=[plugin_name]):
            c_reg.unload()
        self.logger.debug('Liveticker for plugin %s unloaded', plugin_name)

    async def _hourly_timer_coro(self, _job):
        self.logger.debug("Hourly timer schedules liveticker timers for this hour.")
        # TODO Hourly timer

    async def _semiweekly_timer_coro(self, _job):
        """
        Coroutine used by the semi-weekly timer for the scheduling of matches

        :param _job: timer job
        :return: None
        """
        self.logger.debug("Semi-Weekly timer schedules matches.")
        until = self.semiweekly_timer.next_execution()
        for source in LTSource:
            for league_reg in self.registrations[source].values():
                await league_reg.schedule_kickoffs(until)
        Storage().get(self)['next_semiweekly'] = until.strftime("%Y-%m-%d %H:%M")
        Storage().save(self)

    async def get_standings(self, league: str, source: LTSource) -> Tuple[str, Dict[str, List[TableEntry]]]:
        """
        Returns the current standings of that league

        :param league: league key
        :param source: data source
        :raises ValueError: if unable to retrieve any standings information
        :return: league name and current standings per group
        """
        tables = {}
        league_name = league
        if source == LTSource.ESPN:
            data = await restclient.Client("https://site.api.espn.com/apis/v2/sports").request(
                f"/soccer/{league}/standings")
            if 'children' not in data:
                raise ValueError(f"Unable to retrieve any standings information for {league}")
            groups = data['children']
            for group in groups:
                entries = group['standings']['entries']
                group_name = group['name']
                tables[group_name] = [TableEntry(entry, LTSource.ESPN, self.teamname_converter) for entry in entries]
        elif source == LTSource.OPENLIGADB:
            year = (datetime.datetime.today() - datetime.timedelta(days=180)).year
            data = await restclient.Client("https://www.openligadb.de/api").request(f"/getbltable/{league}/{year}")
            table = []
            if not data:
                raise ValueError(f"Unable to retrieve any standings information for {league}")
            for i in range(len(data)):
                data[i]['rank'] = i + 1
                table.append(TableEntry(data[i], LTSource.OPENLIGADB, self.teamname_converter))
            tables[league] = table
        else:
            raise ValueError("Invalid source")
        return league_name, tables
