import asyncio
import datetime
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Generator, Tuple, Optional, Dict, Iterable, Coroutine, Any, Set

from base import BaseSubsystem, BasePlugin
from botutils import restclient
from botutils.converters import get_plugin_by_name
from botutils.utils import execute_anything_sync
from data import Storage, Lang, Config
from subsystems import timers
from subsystems.timers import HasAlreadyRun


class LeagueNotExist(Exception):
    """Exception if league does not exist"""
    pass


class SourceNotSupported(Exception):
    """Exception if given source is not supperted by the function"""
    pass


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
    ABANDONED = ":fire:"
    UNKNOWN = "❔"

    @staticmethod
    def get(m: dict, src: LTSource):
        """
        Returns the current MatchStatus of the match

        :param m: raw match data
        :param src: data source
        :return: MatchStatus
        :rtype: MatchStatus
        :raises SourceNotSupported: if source is not valid
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
                if m.get('status', {}).get('name') == "STATUS_ABANDONED":
                    return MatchStatus.ABANDONED
                if m.get('status', {}).get('name') == "STATUS_POSTPONED":
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
        raise SourceNotSupported


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


class TableEntryBase(ABC):
    """Base class for an entry of a standings table"""

    rank: int
    team: TeamnameDict
    won: int
    draw: int
    lost: int
    goals: int
    goals_against: int
    points: int
    rank_change: int = 0

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


class TableEntryESPN(TableEntryBase):
    """
    Table entry from an ESPN source

    :param data: raw data from the request
    """

    def __init__(self, data: dict):
        stats = {x['name']: (int(x['value']) if x.get('value') is not None else None) for x in data['stats']}
        self.rank = stats.get('rank')
        self.team = Config().bot.liveticker.teamname_converter.get(data['team']['displayName'])
        if not self.team:
            self.team = Config().bot.liveticker.teamname_converter.add(long_name=data['team']['displayName'],
                                                                       short_name=data['team']['shortDisplayName'],
                                                                       abbr=data['team']['abbreviation'])
        self.won = stats.get('wins')
        self.draw = stats.get('ties')
        self.lost = stats.get('losses')
        self.goals = stats.get('pointsFor')
        self.goals_against = stats.get('pointsAgainst')
        self.points = stats.get('points')
        self.rank_change = stats.get('rankChange')


class TableEntryOLDB(TableEntryBase):
    """
    Table entry from an OpenLigaDB source

    :param data: raw data from the request
    """

    def __init__(self, data: dict):
        self.rank = data['rank']
        self.team = Config().bot.liveticker.teamname_converter.get(data['teamName'])
        if not self.team:
            self.team = Config().bot.liveticker.teamname_converter.add(long_name=data['teamName'],
                                                                       short_name=data['shortName'])
        self.won = data['won']
        self.draw = data['draw']
        self.lost = data['lost']
        self.goals = data['goals']
        self.goals_against = data['opponentGoals']
        self.points = data['points']


class MatchBase(ABC):
    """Abstract base class of a match with additional info"""

    match_id: str
    league_key: str
    kickoff: datetime.datetime
    home_team: TeamnameDict
    away_team: TeamnameDict
    home_team_id: str
    away_team_id: str
    minute: str
    status: MatchStatus
    raw_events: list
    new_events: list
    venue: Tuple[str, str]
    score: Dict[str, int]
    matchday: int

    def __init__(self, _m, _league, **kwargs):
        pass

    @classmethod
    def from_storage(cls, m: dict, league_key: str):
        """Build match from storage"""
        match = cls(m, league_key, from_storage=True)
        match.match_id = m['match_id']
        match.kickoff = datetime.datetime.fromisoformat(m['kickoff'])
        match.home_team_id, match.away_team_id = m['teams']
        match.home_team = Config().bot.liveticker.teamname_converter.get(m['teams'][match.home_team_id])
        match.away_team = Config().bot.liveticker.teamname_converter.get(m['teams'][match.away_team_id])
        match.minute = m['minute']
        match.status = MatchStatus[m['status']]
        match.raw_events = []
        match.new_events = []
        match.venue = m['venue']
        match.score = m['score']
        match.matchday = m['matchday']
        return match

    def to_storage(self):
        """Transforming the info to a dict"""
        return {
            'match_id': self.match_id,
            'teams': {
                self.home_team_id: self.home_team.long_name,
                self.away_team_id: self.away_team.long_name
            },
            'kickoff': self.kickoff.isoformat(),
            'minute': self.minute,
            'status': self.status.name,
            'venue': self.venue,
            'score': self.score,
            'matchday': self.matchday
        }

    @abstractmethod
    def transform_events(self, last_events: list):
        """Transforms the raw event data and returns the resulting events"""
        pass

    def display(self):
        return f"{self.minute} | {self.home_team.emoji} {self.home_team.long_name} - " \
               f"{self.away_team.emoji} {self.away_team.long_name} | " \
               f"{self.score[self.home_team_id]}:{self.score[self.away_team_id]}"


class MatchESPN(MatchBase):
    """
    Match from an ESPN source

    :param m: raw data from the request
    :param new_events:
    """

    def __init__(self, m: dict, league_key: str, new_events: list = None, *, from_storage: bool = False):
        super().__init__(m, league_key, from_storage=from_storage)
        if from_storage:
            return
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
                home_team = Config().bot.liveticker.teamname_converter.get(team.get('team', {}).get('displayName'))
                if not home_team:
                    home_team = Config().bot.liveticker.teamname_converter.add(
                        long_name=team.get('team', {}).get('displayName'),
                        short_name=team.get('team', {}).get('shortDisplayName'),
                        abbr=team.get('team', {}).get('abbreviation'))
                home_id = team.get('id')
                home_score = team.get('score')
            elif team.get('homeAway') == "away":
                away_team = Config().bot.liveticker.teamname_converter.get(team.get('team', {}).get('displayName'))
                if not away_team:
                    away_team = Config().bot.liveticker.teamname_converter.add(
                        long_name=team.get('team', {}).get('displayName'),
                        short_name=team.get('team', {}).get('shortDisplayName'),
                        abbr=team.get('team', {}).get('abbreviation'))
                away_id = team.get('id')
                away_score = team.get('score')

        # Put all informations together
        self.match_id = m.get('uid')
        self.league_key = league_key
        self.kickoff = kickoff
        self.minute = m.get('status', {}).get('displayClock')
        self.home_team = home_team
        self.home_team_id = home_id
        self.away_team = away_team
        self.away_team_id = away_id
        self.score = {home_id: home_score, away_id: away_score}
        self.new_events = new_events
        self.raw_events = m.get('competitions', [{}])[0].get('details')
        self.venue = (competition.get('venue', {}).get('fullName'),
                      competition.get('venue', {}).get('address', {}).get('city'))
        self.status = MatchStatus.get(m, LTSource.ESPN)
        self.matchday = -1

    def transform_events(self, last_events: list):
        events = []
        tmp_score = {self.home_team_id: 0, self.away_team_id: 0}
        for e in self.raw_events:
            event = PlayerEventEnum.build_player_event_espn(e, tmp_score.copy())
            if isinstance(event, GoalBase):
                tmp_score = event.score
            if event.event_id not in last_events:
                events.append(event)
        return events


class MatchOLDB(MatchBase):
    """
    Match from an OpenLigaDB source

    :param m: raw data from the request
    """

    def __init__(self, m: dict, league_key: str, new_events: list = None, *, from_storage: bool = False):
        super().__init__(m, league_key, from_storage=from_storage)
        if from_storage:
            return
        if new_events is None:
            new_events = []
        try:
            kickoff = datetime.datetime.strptime(m.get('matchDateTimeUTC'), "%Y-%m-%dT%H:%M:%SZ") \
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

        self.match_id = m.get('matchID')
        self.league_key = league_key
        self.kickoff = kickoff
        self.minute = str(minute)
        self.home_team = Config().bot.liveticker.teamname_converter.get(m.get('team1', {}).get('teamName'),
                                                                        add_if_nonexist=True)
        self.home_team_id = m.get('team1', {}).get('teamId')
        self.away_team = Config().bot.liveticker.teamname_converter.get(m.get('team2', {}).get('teamName'),
                                                                        add_if_nonexist=True)
        self.away_team_id = m.get('team2', {}).get('teamId')
        self.score = {self.home_team_id: max(0, 0, *(g.get('scoreTeam1', 0) for g in m.get('goals', []))),
                      self.away_team_id: max(0, 0, *(g.get('scoreTeam2', 0) for g in m.get('goals', [])))}
        self.raw_events = m.get('goals')
        self.venue = (m['location'].get('locationStadium'), m['location'].get('locationCity')) \
            if 'location' in m and m['location'] is not None else (None, None)
        self.status = MatchStatus.get(m, LTSource.OPENLIGADB)
        self.new_events = new_events
        self.matchday = m.get('group', {}).get('groupOrderID')

    def transform_events(self, last_events: list):
        events = []
        for g in self.raw_events:
            goal = GoalOLDB(g, self.home_team_id, self.away_team_id)
            if goal.event_id not in last_events:
                events.append(goal)
        return events


class PlayerEvent(ABC):
    """Base class for all event types in a match"""

    event_id: str
    player: str
    minute: str

    @abstractmethod
    def display(self):
        pass


class GoalBase(PlayerEvent, ABC):
    """Base class for Goals"""

    score: Dict[str, int]
    is_owngoal: bool
    is_penalty: bool
    is_overtime: bool

    def display(self) -> str:
        if self.is_owngoal:
            return ":soccer::back: {}:{} {} ({})".format(*list(self.score.values())[0:2], self.player, self.minute)
        if self.is_penalty:
            return ":soccer::goal: {}:{} {} ({})".format(*list(self.score.values())[0:2], self.player, self.minute)
        return ":soccer: {}:{} {} ({})".format(*list(self.score.values())[0:2], self.player, self.minute)


class GoalESPN(GoalBase):
    """
    Goal from an ESPN source

    :param g: raw data from the request
    :param score: score dict from before the goal
    """

    def __init__(self, g: dict, score: dict):
        score[g.get('team', {}).get('id')] += g.get('scoreValue')
        self.event_id = "{}/{}/{}".format(g.get('type', {}).get('id'),
                                          g.get('clock', {}).get('value'),
                                          g.get('athletesInvolved', [{}])[0].get('id'))
        self.player = g.get('athletesInvolved', [{}])[0].get('displayName')
        self.minute = g.get('clock', {}).get('displayValue')
        self.score = score
        self.is_owngoal = g.get('ownGoal')
        self.is_penalty = g.get('penaltyKick')
        self.is_overtime = False


class GoalOLDB(GoalBase):
    """
    Goal from an OpenLigaDB source

    :param g: raw data from the request
    :param home_id: id of the home team
    :param away_id: id of the away team
    """

    def __init__(self, g: dict, home_id: str, away_id: str):
        self.event_id = g.get('goalID')
        self.player = g.get('goalGetterName')
        self.minute = g.get('matchMinute')
        self.score = {home_id: g.get('scoreTeam1'), away_id: g.get('scoreTeam2')}
        self.is_owngoal = g.get('isOwnGoal')
        self.is_penalty = g.get('isPenalty')
        self.is_overtime = g.get('isOvertime')


class YellowCardBase(PlayerEvent, ABC):
    """Base class for yellow cards"""

    def display(self):
        return ":yellow_square: {} ({})".format(self.player, self.minute)


class YellowCardESPN(YellowCardBase):
    """
    Yellow card from an ESPN source

    :param yc: raw data from the request
    """

    def __init__(self, yc: dict):
        self.event_id = "{}/{}/{}".format(yc.get('type', {}).get('id'),
                                          yc.get('clock', {}).get('value'),
                                          yc.get('athletesInvolved', [{}])[0].get('id'))
        self.player = yc.get('athletesInvolved', [{}])[0].get('displayName')
        self.minute = yc.get('clock', {}).get('displayValue')


class RedCardBase(PlayerEvent, ABC):
    """Base class for red cards"""

    def display(self):
        return ":red_square: {} ({})".format(self.player, self.minute)


class RedCardESPN(RedCardBase):
    """
    Red card from an ESPN source

    :param rc: raw data from the request
    """

    def __init__(self, rc: dict):
        self.event_id = "{}/{}/{}".format(rc.get('type', {}).get('id'),
                                          rc.get('clock', {}).get('value'),
                                          rc.get('athletesInvolved', [{}])[0].get('id'))
        self.player = rc.get('athletesInvolved', [{}])[0].get('displayName')
        self.minute = rc.get('clock', {}).get('displayValue')


class PlayerEventEnum(Enum):
    """Enum for the different types of PlayerEvents"""
    GOAL = GoalBase
    YELLOWCARD = YellowCardBase
    REDCARD = RedCardBase
    UNKNOWN = None

    @classmethod
    def _missing_(cls, _):
        return PlayerEventEnum.UNKNOWN

    @staticmethod
    def build_player_event_espn(event: dict, score: dict) -> PlayerEvent:
        """
        Builds the corresponding PlayerEvent from the given event dict. ESPN only

        :param event: event data dictionary
        :param score: current score
        :return: Goal/RedCard/YellowCard
        :raises ValueError: when event type does not match with the expected values
        """
        if event.get('scoringPlay'):
            return GoalESPN(event, score)
        if event.get('type', {}).get('id') == "93":
            return RedCardESPN(event)
        if event.get('type', {}).get('id') == "94":
            return YellowCardESPN(event)
        raise ValueError("Unexpected event type {}: {}".format(event.get('type', {}).get('id'),
                                                               event.get('type', {}).get('name')))


class LivetickerEvent:
    def __init__(self, league: str, matches: Iterable[MatchBase]):
        self.league = league
        self.matches = matches


class LivetickerKickoff(LivetickerEvent):
    def __init__(self, league: str, matches: Iterable[MatchBase], kickoff: datetime.datetime):
        super().__init__(league, matches)
        self.kickoff = kickoff


class LivetickerUpdate(LivetickerEvent):
    """
    LivetickerEvent for the mid-game update

    :param league: league of the Registration
    :param matches: current matches
    :param new_events: dictionary of the new events per match
    """

    def __init__(self, league: str, matches: Iterable[MatchBase], new_events: dict):
        m_list = []
        for m in matches:
            m.new_events = new_events.get(m.match_id)
            m_list.append(m)
        super().__init__(league, m_list)


class LivetickerFinish(LivetickerEvent):
    pass


class CoroRegistrationBase(ABC):
    """Registration for a single Coroutine. Liveticker updates for the specified league will be transmitted to the
    specified coro

    :param league_reg: Registration of the corresponding league
    :type league_reg: LeagueRegistrationBase
    :param coro: Coroutine which receives the LivetickerEvents
    :param periodic: whether the registration should receive mid-game updates"""

    def __init__(self, league_reg, plugin, coro, interval: int, periodic: bool = False):
        self.league_reg = league_reg
        self.plugin_name = plugin.get_name()
        self.coro = coro
        self.periodic = periodic
        self.__interval = interval
        self.last_events = {}
        self.logger = logging.getLogger(__name__)

    @property
    def interval(self):
        return self.__interval

    @interval.setter
    def interval(self, interval):
        self.__interval = interval
        self.league_reg.store_c_regs()
        execute_anything_sync(self.league_reg.listener.request_match_timer_update)

    async def deregister(self):
        await self.league_reg.deregister_coro(self)

    async def unload(self):
        await self.league_reg.unload_coro(self)

    def next_kickoff(self):
        """Returns datetime of the next match"""
        return self.league_reg.next_kickoff()

    async def update(self, matches: List[MatchBase]):
        """
        Coroutine used by the interval timer during matches. Manufactures the LivetickerUpdate for the coro.
        """
        self.logger.debug("CoroReg updates.")
        new_events = {}
        for m in matches:
            if m.match_id not in self.last_events:
                self.last_events[m.match_id] = []
            events = m.transform_events(self.last_events[m.match_id])
            new_events[m.match_id] = events
            self.last_events[m.match_id].extend([e.event_id for e in events])
        await self.coro(LivetickerUpdate(self.league_reg.league, matches, new_events))

    async def update_kickoff(self, time_kickoff: datetime.datetime, matches: Iterable[MatchBase]):
        await self.coro(LivetickerKickoff(self.league_reg.league, matches, time_kickoff))

    async def update_finished(self, match_list):
        await self.coro(LivetickerFinish(self.league_reg.league, match_list))

    def storage(self):
        return {
            'plugin': self.plugin_name,
            'coro': self.coro.__name__,
            'interval': self.interval,
            'periodic': self.periodic
        }

    def __eq__(self, other):
        return self.coro == other.coro and self.periodic == other.periodic

    def __str__(self):
        return "<liveticker.CoroRegistration; coro={}; periodic={}; interval={}>" \
            .format(self.coro, self.periodic, self.interval)

    def __bool__(self):
        return self.league_reg.__bool__()


class CoroRegistrationESPN(CoroRegistrationBase):
    pass


class CoroRegistrationOLDB(CoroRegistrationBase):
    pass


class LeagueRegistrationBase(ABC):
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
        self.registrations: List[CoroRegistrationBase] = []
        self.logger = logging.getLogger(__name__)
        self.kickoffs: Dict[datetime.datetime, Dict[str, MatchBase]] = {}
        self.finished = []

    @property
    def intervals(self):
        return [c_reg.interval for c_reg in self.registrations]

    @property
    def matches(self):
        return [s[i] for s in self.kickoffs.values() for i in s]

    @classmethod
    async def create(cls, listener, league: str, source: LTSource):
        """New LeagueRegistration"""
        l_reg = cls(listener, league, source)
        await l_reg.schedule_kickoffs(until=listener.semiweekly_timer.next_execution())
        return l_reg

    @classmethod
    async def restore(cls, listener, league: str, source: LTSource):
        """Restored LeagueRegistration"""
        l_reg = cls(listener, league, source)
        kickoff_data = Storage().get(listener)['registrations'][source.value][league]['kickoffs']
        for raw_kickoff, matches_ in list(kickoff_data.items()):
            time_kickoff = datetime.datetime.strptime(raw_kickoff, "%Y-%m-%d %H:%M")
            if datetime.datetime.now() - time_kickoff > datetime.timedelta(hours=3.5):
                l_reg.logger.debug("Discard old kickoff %s. Timed out.", raw_kickoff)
                Storage().get(listener)['registrations'][source.value][league]['kickoffs'].pop(raw_kickoff)
                Storage().save(listener)
                continue
            matches = {}
            for m in matches_:
                match = cls.get_matchclass().from_storage(m, league)
                matches[match.match_id] = match
            l_reg.kickoffs[time_kickoff] = matches
        return l_reg

    @abstractmethod
    async def register(self, plugin, coro, interval: int, periodic: bool) -> CoroRegistrationBase:
        """Builds and registers a CoroReg for this league"""
        pass

    @staticmethod
    @abstractmethod
    def get_matchclass():
        pass

    async def register_c_reg(self, c_reg: CoroRegistrationBase):
        """Registers the registration"""
        if c_reg not in self.registrations:
            self.registrations.append(c_reg)
            self.store_c_regs()
        return c_reg

    async def deregister(self):
        """Deregisters this LeagueReg correctly"""
        await self.listener.deregister(self)

    async def unload(self):
        """Unloads this LeagueRegistration"""
        await self.listener.unload(self)

    async def deregister_coro(self, c_reg: CoroRegistrationBase):
        """Finishes the deregistration of a CoroRegistration"""
        if c_reg in self.registrations:
            self.registrations.remove(c_reg)
            self.store_c_regs()
        if not self.registrations:
            await self.deregister()

    async def unload_coro(self, coro: CoroRegistrationBase):
        """Finishes the unloading of a CoroRegistration"""
        if coro in self.registrations:
            self.registrations.remove(coro)
        if not self.registrations:
            await self.unload()

    def store_c_regs(self):
        """Updates the storage in terms of the CoroRegistrations registrated"""
        l_storage = Storage().get(self.listener)['registrations'][self.source.value][self.league]
        c_storages = []
        # Rescue unloaded c_regs
        loaded_plugins = self.listener.bot.get_normalplugins()
        for c_storage in l_storage['coro_regs']:
            if c_storage['plugin'] not in loaded_plugins:
                c_storages.append(c_storage)
        # Store loaded c_regs
        for c_reg in self.registrations:
            c_storages.append(c_reg.storage())
        # Save to storage
        l_storage['coro_regs'] = c_storages
        Storage().save(self.listener)

    def store_matches(self):
        """Updates the storage in terms of the matches saved"""
        Storage().get(self.listener)['registrations'][self.source.value][self.league]['kickoffs'] = {}
        for kickoff, matches in self.kickoffs.items():
            Storage().get(self.listener)['registrations'][self.source.value][self.league]['kickoffs'][
                kickoff.strftime("%Y-%m-%d %H:%M")] = [m.to_storage() for m in matches.values()]
        Storage().save(self.listener)

    async def update_matches(self):
        """Updates and returns the matches and current standings of the league. No new matches inserted!"""
        matches = await self.get_matches_by_date(self.league)

        for match in matches:
            if match.kickoff not in self.kickoffs:
                continue
            if match.match_id not in self.kickoffs[match.kickoff]:
                continue
            self.kickoffs[match.kickoff][match.match_id] = match
        self.store_matches()
        return self.matches

    @staticmethod
    @abstractmethod
    async def get_matches_by_date(league: str, from_day: datetime.date = None, until_day: datetime.date = None,
                                  limit_pages: int = 5) -> List[MatchBase]:
        """
        Requests match data for a specific data range.

        :param league: league key
        :param from_day: start of the date range
        :param until_day: end of the date range
        :param limit_pages: maximum number of requests to get the matches in this range.
        :return: List of corresponding matches
        """
        pass

    @staticmethod
    @abstractmethod
    async def get_standings(league: str) -> Dict[str, List[TableEntryBase]]:
        """
        Returns the current standings of that league

        :param league: key of the league
        :raises SourceNotSupported: if source type is not covered
        :raises LeagueNotExist: if league key doesnt lead to a valid league
        :return: league name and current standings per group
        """
        pass

    async def schedule_kickoffs(self, until: datetime.datetime):
        """
        Schedules timers for the kickoffs of the matches until the specified date

        :param until: datetime of the day before the next semi-weekly execution
        :raises ValueError: if source does not provide support scheduling of kickoffs
        """
        self.kickoffs: Dict[datetime.datetime, Dict[str, MatchBase]] = {}
        now = datetime.datetime.now()
        Storage().get(self.listener)['registrations'][self.source.value][self.league]['kickoffs'] = {}

        matches: List[MatchBase] = await self.get_matches_by_date(league=self.league, from_day=now.date(),
                                                                  until_day=until.date())

        # Group by kickoff
        for match in matches:
            if match.status in [MatchStatus.COMPLETED, MatchStatus.POSTPONED, MatchStatus.ABANDONED] \
                    or match.kickoff > until:
                continue
            if match.kickoff not in self.kickoffs:
                self.kickoffs[match.kickoff] = {}
            self.kickoffs[match.kickoff][match.match_id] = match

        # Store matches
        self.store_matches()

    def next_kickoff(self):
        """Returns datetime of the next match"""
        kickoffs = list(self.kickoffs.keys())
        if kickoffs:
            return min(kickoffs)
        return None

    async def update_periodic_coros(self, kickoffs: Set[datetime.datetime]):
        """
        Regularly updates coros and checks if matches are still running.

        :param kickoffs: List of kickoff datetimes
        :return:
        """

        self.logger.debug("update_periodic_coro for kickoffs %s", kickoffs)
        await self.update_matches()
        # Sort matches
        matches = []
        new_finished = []
        now = datetime.datetime.now().replace(second=0, microsecond=0)
        for kickoff in kickoffs.copy():
            if kickoff not in self.kickoffs:
                # NotFound
                kickoffs.remove(kickoff)
            elif datetime.datetime.now() - kickoff > datetime.timedelta(hours=3.5):
                # Timeout
                new_finished.extend(self.kickoffs[kickoff].values())
                kickoffs.remove(kickoff)
            elif kickoff == now:
                # Kickoff
                for c_reg in self.registrations:
                    await c_reg.update_kickoff(kickoff, self.kickoffs[kickoff].values())
                kickoffs.remove(kickoff)
            else:
                # Update
                for match in self.kickoffs[kickoff].values():
                    if match.status in (MatchStatus.COMPLETED, MatchStatus.POSTPONED, MatchStatus.ABANDONED):
                        new_finished.append(match)
                    matches.append(match)
        # Update matches c_reg
        for c_reg in self.registrations:
            c_reg_matches = []
            for match in matches:
                if ((now - match.kickoff) // datetime.timedelta(minutes=1)) % c_reg.interval == 0:
                    c_reg_matches.append(match)
            if c_reg_matches and c_reg.periodic:
                await c_reg.update(c_reg_matches)
        # Clear finished matches
        do_request: bool = False
        new_finished = [e for e in new_finished if e.match_id not in self.finished]  # Just to be safe
        self.finished.extend([m.match_id for m in new_finished])
        for match in new_finished:
            self.kickoffs[match.kickoff].pop(match.match_id)
            if len(self.kickoffs[match.kickoff]) == 0:
                do_request = True
                self.kickoffs.pop(match.kickoff)
        if new_finished:
            self.store_matches()
        for c_reg in self.registrations:
            await c_reg.update_finished(new_finished)
        if do_request:
            await self.listener.request_match_timer_update()

    def __str__(self):
        return f"<liveticker.LeagueRegistration; league={self.league}; src={self.source.value}; " \
               f"regs={len(self.registrations)}; kickoffs={len(self.kickoffs)}>"

    def __bool__(self):
        return bool(self.kickoffs)


class LeagueRegistrationESPN(LeagueRegistrationBase):
    """LeagueRegistration for ESPN sources"""

    async def register(self, plugin, coro, interval: int, periodic: bool):
        reg = CoroRegistrationESPN(self, plugin=plugin, coro=coro, interval=interval, periodic=periodic)
        return await self.register_c_reg(reg)

    @staticmethod
    async def get_matches_by_date(league: str, from_day: datetime.date = None, until_day: datetime.date = None,
                                  limit_pages: int = 1) -> List[MatchESPN]:
        if from_day is None:
            from_day = datetime.date.today()
        if until_day is None:
            until_day = from_day

        dates = "{}-{}".format(from_day.strftime("%Y%m%d"), until_day.strftime("%Y%m%d"))
        data = await restclient.Client("http://site.api.espn.com/apis/site/v2/sports") \
            .request(f"/soccer/{league}/scoreboard", params={'dates': dates,
                                                             'geckirandom': datetime.datetime.now().microsecond})
        matches = [MatchESPN(x, league) for x in data['events']]
        return matches

    @staticmethod
    async def get_standings(league: str):
        tables = {}
        data = await restclient.Client("https://site.api.espn.com/apis/v2/sports").request(
            f"/soccer/{league}/standings", params={'geckirandom': datetime.datetime.now().microsecond})
        if 'children' not in data:
            raise LeagueNotExist(f"Unable to retrieve any standings information for {league}")
        groups = data['children']
        for group in groups:
            entries = group['standings']['entries']
            group_name = group['name']
            tables[group_name] = [TableEntryESPN(entry) for entry in entries]
        return tables

    @staticmethod
    def get_matchclass():
        return MatchESPN


class LeagueRegistrationOLDB(LeagueRegistrationBase):
    """LeagueRegistration for OpenLigaDB sources"""

    async def register(self, plugin, coro, interval: int, periodic: bool):
        reg = CoroRegistrationOLDB(self, plugin=plugin, coro=coro, interval=interval, periodic=periodic)
        return await self.register_c_reg(reg)

    @staticmethod
    async def get_matches_by_date(league: str, from_day: datetime.date = None, until_day: datetime.date = None,
                                  limit_pages: int = 5) -> List[MatchOLDB]:
        """
        Requests openligadb match data for a specified date range. Doesn't support past days or dates too far into
        future since it is all matchday-based and starts from the present matchday.

        :param league: league key
        :param from_day: start of the date range. No past days supported.
        :param until_day: end of the date range.
        :param limit_pages: maximum number of requests respectivly the number of matchdays checked for fitting matches.
        :return: List of the corresponding matches
        """
        if from_day is None:
            from_day = datetime.date.today()
        if until_day is None:
            until_day = from_day

        data = await restclient.Client("https://api.openligadb.de").request("/getmatchdata/{}".format(league))
        matches = []
        if not data:
            return []
        for m in data:
            match = MatchOLDB(m, league)
            if match.kickoff.date() > until_day:
                break
            if match.kickoff.date() >= from_day:
                matches.append(match)
        else:
            for _ in range(1, limit_pages):
                add_matches = await LeagueRegistrationOLDB.get_matches_by_matchday(league=league,
                                                                                   matchday=matches[-1].matchday)
                if not add_matches:
                    break
                matches.extend(add_matches)
        return matches

    @staticmethod
    async def get_matches_by_matchday(league: str, matchday: int, season: int = None) -> List[MatchOLDB]:
        """
        Requests openligadb match data for a specified matchday

        :param league: league key
        :param matchday: Requested matchday
        :param season: season/year
        :return: List of the corresponding matches
        """
        if season is None:
            date = datetime.date.today()
            season = date.year if date.month > 6 else date.year - 1
        data = await restclient.Client("https://api.openligadb.de").request(
            f"/getmatchdata/{league}/{season}/{matchday}")
        return [MatchOLDB(m, league) for m in data]

    @staticmethod
    async def get_standings(league: str):
        tables = {}
        year = (datetime.datetime.today() - datetime.timedelta(days=180)).year
        data = await restclient.Client("https://api.openligadb.de").request(f"/getbltable/{league}/{year}")
        table = []
        if not data:
            raise LeagueNotExist(f"Unable to retrieve any standings information for {league}")
        for i in range(len(data)):
            data[i]['rank'] = i + 1
            table.append(TableEntryOLDB(data[i]))
        tables[league] = table
        return tables

    def matchday(self):
        """Returns the current matchday (OLDB only)"""
        if self.source == LTSource.OPENLIGADB:
            for match in self.matches:
                md = match.matchday
                if md:
                    return md
        return None

    @staticmethod
    def get_matchclass():
        return MatchOLDB


class Liveticker(BaseSubsystem):
    """Subsystem for the registration and operation of sports livetickers"""

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.registrations = {x: {} for x in LTSource}
        self.teamname_converter = TeamnameConverter(self)
        self.restored = False
        self.match_timer = None
        self.__last_match_timer_update = datetime.datetime.min
        self.hourly_timer = None
        self.semiweekly_timer = None

        self.update_storage()

        # pylint: disable=unused-variable
        @bot.listen()
        async def on_ready():
            plugins = self.bot.get_normalplugins()
            await self.restore(plugins)
            self.restored = True
            # Semiweekly timer to get coming matches
            self.semiweekly_timer = self.bot.timers.schedule(coro=self._semiweekly_timer_coro,
                                                             td=timers.timedict(weekday=[2, 5], hour=[3], minute=[55]))
            if Storage().get(self).get('next_semiweekly') is None or \
                    datetime.datetime.strptime(Storage().get(self)['next_semiweekly'], "%Y-%m-%d %H:%M") \
                    < datetime.datetime.now():
                self.semiweekly_timer.execute()
            # Hourly timer to schedule the timer the LeagueReg updates
            self.hourly_timer = self.bot.timers.schedule(coro=self._hourly_timer_coro, td=timers.timedict(minute=0))
            self.hourly_timer.execute()

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

    def update_storage(self):
        """Storage update at version jump"""
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
        if Storage().get(self).get('storage_version') < 2:
            for src in Storage().get(self)['registrations'].values():
                for reg in src.values():
                    reg['kickoffs'] = {kickoff: [] for kickoff in reg['kickoffs']}
            Storage().get(self)['storage_version'] = 2
        Storage().save(self)

    async def register(self, league: str, raw_source: str, plugin: BasePlugin,
                       coro, interval: int = 15, periodic: bool = True) -> CoroRegistrationBase:
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
            l_reg_class = LeagueRegistrationESPN if source == LTSource.ESPN else LeagueRegistrationOLDB
            if league_exists:
                self.registrations[source][league] = await l_reg_class.restore(self, league, source)
            else:
                self.registrations[source][league] = await l_reg_class.create(self, league, source)
        coro_reg = await self.registrations[source][league].register(plugin, coro, interval, periodic)
        if self.restored:
            await self.request_match_timer_update()
        return coro_reg

    async def deregister(self, reg: LeagueRegistrationBase):
        """
        Finishes the deregistration of a LeagueRegistration

        :param reg: LeagueRegistration
        """
        await self.unload(reg)
        if reg.league in Storage().get(self)['registrations'][reg.source.value]:
            Storage().get(self)['registrations'][reg.source.value].pop(reg.league)
            Storage().save(self)

    async def unload(self, reg: LeagueRegistrationBase):
        if reg.league in self.registrations[reg.source]:
            self.registrations[reg.source].pop(reg.league)
        await self.request_match_timer_update()

    def search_league(self, sources=None, leagues=None) -> Generator[LeagueRegistrationBase, None, None]:
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
                l_reg: LeagueRegistrationBase
                if leagues and league not in leagues:
                    continue
                yield l_reg

    def search_coro(self, plugins: list = None, sources: list = None, leagues: list = None) -> \
            Generator[Tuple[LTSource, str, CoroRegistrationBase], None, None]:
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
        l_reg: LeagueRegistrationBase
        for l_reg in self.search_league(sources=sources, leagues=leagues):
            c_reg: CoroRegistrationBase
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
                                                periodic=c_reg['periodic'],
                                                interval=c_reg.get('interval', 15))
        self.logger.debug('%d Liveticker registrations restored. %d failed.', i, j)

    def unload_plugin(self, plugin_name: str):
        """
        Unloads all active registrations belonging to the specified plugin

        :param plugin_name: name of the plugin
        """
        for _, _, c_reg in self.search_coro(plugins=[plugin_name]):
            c_reg.unload()
        self.logger.debug('Liveticker for plugin %s unloaded', plugin_name)

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

    async def _hourly_timer_coro(self, _job):
        """
        Coroutine used be the hourly timer to set the minutes in the following hour when one or more LeagueRegistrations
        should update.

        :param _job: timer job
        :return: None
        """
        self.logger.debug("Hourly timer schedules timer.")
        await self.request_match_timer_update(from_hourly_timer=True)

    async def request_match_timer_update(self, from_hourly_timer: bool = False):
        """
        Requests an update of the match timer, but ensures that it doesn't update too close to the last update

        :param from_hourly_timer: Trigger an update if the current minute is valid for update. Only used by hourly
        timer.
        """
        time_diff = datetime.datetime.now() - self.__last_match_timer_update
        self.logger.debug("Timediff: %s", time_diff)
        if time_diff >= datetime.timedelta(seconds=10):
            # Update instantly
            self.__last_match_timer_update = datetime.datetime.now()
            self._build_match_timer(from_hourly_timer=from_hourly_timer)
        elif time_diff > datetime.timedelta(0):
            # Last update too close, wait!
            self.__last_match_timer_update += datetime.timedelta(seconds=10)
            self.logger.debug("Wait for %s seconds.", 10 - time_diff.total_seconds())
            await asyncio.sleep(10 - time_diff.seconds)
            self._build_match_timer(from_hourly_timer=from_hourly_timer)
        else:
            # Update already scheduled, no actions needed
            return

    def _build_match_timer(self, from_hourly_timer: bool = False):
        """
        Updates the match timer with the needed minutes and LeagueRegistrations it needs to updates at those minutes

        :param from_hourly_timer: Trigger an update if the current minute is valid for update. Only used by hourly
        timer.
        """
        self.logger.debug("Updating match timer")

        # Cancel old timer
        if self.match_timer and not self.match_timer.cancelled:
            try:
                self.match_timer.cancel()
            except (RuntimeError, HasAlreadyRun):
                pass

        # Calculate minutes
        update_minutes = {x: {} for x in range(61)}
        now = datetime.datetime.now()
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + datetime.timedelta(hours=1)

        data = []
        for l_regs in self.registrations.values():
            for l_reg in l_regs.values():
                for kickoff in l_reg.kickoffs:
                    if kickoff < hour_end:
                        data.extend((l_reg, kickoff, ival) for ival in l_reg.intervals)
        for l_reg, kickoff, ival in data:
            for minute in range((kickoff - hour_start) // datetime.timedelta(minutes=1), 60, ival):
                if minute < 0:
                    continue
                if l_reg not in update_minutes[minute]:
                    update_minutes[minute][l_reg] = set()
                update_minutes[minute][l_reg].add(kickoff)

        # Clean and schedule
        for k, v in list(update_minutes.items()):
            if not v:
                update_minutes.pop(k)
        self.logger.debug("Minutes: %s", list(update_minutes.keys()))
        if not update_minutes:
            return
        self.match_timer = self.bot.timers.schedule(coro=self._update_league_registrations,
                                                    td=timers.timedict(hour=now.hour,
                                                                       minute=list(update_minutes.keys())),
                                                    data=update_minutes)
        if from_hourly_timer and (now.minute in update_minutes or self.match_timer.next_execution() <= now):
            self.match_timer.execute()

    async def _update_league_registrations(self, job):
        try:
            l_regs = job.data[(datetime.datetime.now() + datetime.timedelta(seconds=2)).minute]
        except KeyError:
            self.logger.debug("INVALID UPDATE MINUTE")
            return
        for l_reg, kickoffs in l_regs.items():
            await l_reg.update_periodic_coros(kickoffs.copy())

    @staticmethod
    async def get_standings(league: str, source: LTSource) \
            -> Tuple[str, Coroutine[Any, Any, Dict[str, List[TableEntryBase]]]]:
        """
        Returns the current standings of that league

        :param league: league key
        :param source: data source
        :raises SourceNotSupported: if source type is not covered
        :raises LeagueNotExist: if league key doesnt lead to a valid league
        :return: league name and current standings per group
        """
        if source == LTSource.ESPN:
            tables = await LeagueRegistrationESPN.get_standings(league)
        elif source == LTSource.OPENLIGADB:
            tables = await LeagueRegistrationOLDB.get_standings(league)
        else:
            raise SourceNotSupported
        return league, tables
