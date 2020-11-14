import random
from datetime import datetime, timedelta
from enum import Enum
from typing import Tuple

from botutils.sheetsclient import Cell
from conf import Storage


class LeagueNotFound(Exception):
    pass


class MatchResult(Enum):
    HOME = -1
    DRAW = 0
    AWAY = 1
    NONE = None


class MatchStatus(Enum):
    CLOSED = ":ballot_box_with_check:"
    RUNNING = ":green_square:"
    UPCOMING = ":clock4:"
    UNKNOWN = "❔"


def is_teamname_abbr(team):
    return team is not None and len(team) <= 3


class TeamnameDict:
    """
    Class to convert teamnames into a standardized abbrevation and long form
    """
    def __init__(self, plugin):
        self.teamdict = {}
        teamnames = Storage().get(plugin)['teamnames']
        for long_name, team in teamnames.items():
            self.teamdict[team['short_name'].lower()] = long_name
            self.teamdict[long_name.lower()] = team['short_name']
        for long_name, team in teamnames.items():
            for name in team['other']:
                if is_teamname_abbr(name):
                    # Abbreviation
                    self.teamdict.setdefault(name.lower(), long_name)
                else:
                    # Long name
                    self.teamdict.setdefault(name.lower(), team['short_name'])

    def get_long(self, team):
        if team is None:
            return None
        name = self.teamdict.get(team.lower())
        if is_teamname_abbr(name):
            name = self.teamdict.get(name.lower())
        return name

    def get_abbr(self, team):
        if team is None:
            return None
        name = self.teamdict.get(team.lower())
        if not is_teamname_abbr(name):
            name = self.teamdict.get(name.lower())
        return name


def valid_pred(pred: tuple):
    """
    Returns True if prediction is a valid representation of two integers
    """
    try:
        int(pred[0]), int(pred[1])
    except ValueError:
        return False
    else:
        return True


def pred_reachable(score: Tuple[int, int], pred: Tuple[int, int]):
    """
    Returns True if the prediction can still be matched given the current score
    """
    return score[0] <= pred[0] and score[1] <= pred[1]


def points(score: Tuple[int, int], pred: Tuple[int, int]):
    """
    Returns the points resulting from this score and prediction
    """
    score, pred = (int(score[0]), int(score[1])), (int(pred[0]), int(pred[1]))
    if score == pred:
        return 4
    elif (score[0] - score[1]) == (pred[0] - pred[1]):
        return 3
    elif ((score[0] - score[1]) > 0) - ((score[0] - score[1]) < 0) \
            == ((pred[0] - pred[1]) > 0) - ((pred[0] - pred[1]) < 0):
        return 2
    else:
        return 0


def pointdiff_possible(score: Tuple[int, int], pred1: Tuple[int, int], pred2: Tuple[int, int]):
    """
    Returns the maximal point difference possible at a single match
    """
    if not valid_pred(score):
        # No Score
        if valid_pred(pred1) and valid_pred(pred2):
            p = 4 - points(pred1, pred2)
            diff1, diff2 = p, p
        elif not valid_pred(pred1) and not valid_pred(pred2):
            diff1, diff2 = 0, 0
        elif not valid_pred(pred1):
            diff1, diff2 = 0, 4
        else:
            diff1, diff2 = 4, 0
    else:
        # Running Game
        if not valid_pred(pred1) and not valid_pred(pred2):
            # Both not existent
            diff1, diff2 = 0, 0
        elif valid_pred(pred1) and not valid_pred(pred2):
            # No Away
            diff1 = (3 + pred_reachable(score, pred1)) - points(score, pred1)
            diff2 = points(score, pred1)
        elif valid_pred(pred2) and not valid_pred(pred1):
            # No Home
            diff1 = points(score, pred2)
            diff2 = (3 + pred_reachable(score, pred2)) - points(score, pred2)
        else:
            # Both existent
            if pred1 == pred2:
                diff1, diff2 = 0, 0
            else:
                diff1 = (3 + pred_reachable(score, pred1) - points(pred1, pred2)) \
                        - (points(score, pred1) - points(score, pred2))
                diff2 = (3 + pred_reachable(score, pred2) - points(pred1, pred2)) \
                        - (points(score, pred2) - points(score, pred1))

    return diff1, diff2


def determine_winner(points_h: str, points_a: str, diff_h: int, diff_a: int):
    """
    Determines the winner of a duel
    :param points_h: current points of user 1
    :param points_a: current points of user 2
    :param diff_h: maximum points user 1 can catch up
    :param diff_a: maximum points user 2 can catch up
    :return: MatchResult
    """
    try:
        points_h = int(points_h)
    except (ValueError, TypeError):
        points_h = 0
    try:
        points_a = int(points_a)
    except (ValueError, TypeError):
        points_a = 0

    if points_h > (points_a + diff_a):
        return MatchResult.HOME
    elif points_a > (points_h + diff_h):
        return MatchResult.AWAY
    elif points_h == points_a and diff_h == 0 and diff_a == 0:
        return MatchResult.DRAW
    else:
        return MatchResult.NONE

def convert_to_datetime(day, time):
    if type(day) == int:
        day_ = datetime(1899, 12, 30) + timedelta(days=day)
    else:
        try:
            date = [int(x) for x in day.split(".") if x != ""]
            if len(date) < 3:
                date.append(datetime.today().year)
            day_ = datetime(*date[::-1])
        except (TypeError, ValueError):
            day_ = datetime.today()
    if type(time) == float:
        time_ = datetime(1, 1, 1) + timedelta(days=time)
    else:
        try:
            time_ = datetime.strptime(time, "%H:%M")
        except (TypeError, ValueError):
            time_ = datetime.now()
    return datetime.combine(day_.date(), time_.time())

def match_status(day, time=None):
    """
    Checks the status of a match (Solely time-based)

    :param day: datetime or day of kick-off
    :param time: time of kick-off
    :return: CLOSED for finished matches, RUNNING for currently active matches (2 hours after kickoff) and UPCOMING
    for matches not started. UNKNOWN if unable to read the date or time
    """
    if type(day) == datetime:
        match_datetime = day
    else:
        match_datetime = convert_to_datetime(day, time)

    now = datetime.now()
    try:
        timediff = (now - match_datetime).total_seconds()
        if timediff < 0:
            return MatchStatus.UPCOMING
        elif timediff < 7200:
            return MatchStatus.RUNNING
        else:
            return MatchStatus.CLOSED
    except ValueError:
        return MatchStatus.UNKNOWN


def get_user_league(plugin, user: str):
    """
    Returns the league of the user

    :return: number of the league
    """
    for league, participants in Storage().get(plugin)['participants'].items():
        if user.lower() in (x.lower() for x in participants):
            return league
    else:
        raise UserNotFound(user)


def get_user_cell(plugin, user: str):
    """
    Returns the position of the user's title cell in the 'Tipps' section

    :return: (col, row) of the cell
    """
    for league, participants in Storage().get(plugin)['participants'].items():
        for i in range(len(participants)):
            if user.lower() == participants[i].lower():
                return Cell(column=60 + (2 * i), row=12 * (int(league) - 1) + 2)
    else:
        raise UserNotFound(user)


def get_schedule(plugin, league, matchday: int):
    matchday = [3, 14, 13, 16, 12, 9, 8, 4, 15, 10, 11, 7, 1, 5, 6, 0, 2][matchday - 1]  # "Randomize" input
    participants = Storage().get(plugin)['participants'].get(league)
    if participants is None:
        raise LeagueNotFound()
    participants.extend([None] * max(0, 18 - len(participants)))  # Extend if not enough participants
    p = [participants[i] for i in [11, 0, 13, 6, 5, 15, 9, 1, 14, 8, 4, 16, 7, 2, 17, 3, 10, 12]]
    p = p[0:1] + p[1:][matchday:] + p[1:][:matchday]
    schedule = []
    schedule.extend([(p[0], p[1]),
                     (p[2], p[17]),
                     (p[3], p[16]),
                     (p[4], p[15]),
                     (p[5], p[14]),
                     (p[6], p[13]),
                     (p[7], p[12]),
                     (p[8], p[11]),
                     (p[9], p[10])])
    random.shuffle(schedule)
    return schedule


def get_schedule_opponent(plugin, participant, matchday: int):
    league = get_user_league(plugin, participant)
    schedule = get_schedule(plugin, league, matchday)
    for home, away in schedule:
        if home == participant:
            return away
        if away == participant:
            return home
    else:
        return None


class UserNotFound(Exception):
    def __init__(self, user):
        self.user = user