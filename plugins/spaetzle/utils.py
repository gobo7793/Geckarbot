from datetime import datetime
from enum import Enum
from typing import Tuple

from conf import Storage


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
        name = self.teamdict.get(team.lower())
        if is_teamname_abbr(name):
            name = self.teamdict.get(name.lower())
        return name

    def get_abbr(self, team):
        name = self.teamdict.get(team.lower())
        if not is_teamname_abbr(name):
            name = self.teamdict.get(name.lower())
        return name


def valid_pred(pred: tuple):
    try:
        int(pred[0]), int(pred[1])
    except ValueError:
        return False
    else:
        return True


def pred_reachable(score: Tuple[int, int], pred: Tuple[int, int]):
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


def match_status(match_datetime: datetime):
    """
    Checks the status of a match (Solely time-based)

    :param match_datetime: datetime of kick-off
    :return: CLOSED for finished matches, RUNNING for currently active matches (2 hours after kickoff) and UPCOMING
    for matches not started. UNKNOWN if unable to read the date or time
    """
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