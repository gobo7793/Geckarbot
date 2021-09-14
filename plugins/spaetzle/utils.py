import random
from datetime import datetime, timedelta
from enum import Enum
from typing import Tuple, Union, Optional

from botutils.sheetsclient import Cell, CellRange
from data import Storage
from services.liveticker import MatchStatus


class LeagueNotFound(Exception):
    """League is not valid"""
    pass


class UserNotFound(Exception):
    """User is not a valid Spaetzle participant"""
    def __init__(self, user):
        super().__init__()
        self.user = user


class MatchResult(Enum):
    """Result of a match"""
    HOME = -1
    DRAW = 0
    AWAY = 1
    NONE = None


def valid_pred(pred: tuple) -> bool:
    """
    Returns True if prediction is a valid representation of two integers
    """
    try:
        int(pred[0]), int(pred[1])
    except ValueError:
        return False
    else:
        return True


def pred_reachable(score: Tuple[int, int], pred: Tuple[int, int]) -> bool:
    """
    Returns True if the prediction can still be matched given the current score
    """
    return score[0] <= pred[0] and score[1] <= pred[1]


def points(score: Tuple[int, int], pred: Tuple[int, int]) -> int:
    """
    Returns the points resulting from this score and prediction
    """
    score, pred = (int(score[0]), int(score[1])), (int(pred[0]), int(pred[1]))
    if score == pred:
        return 4
    if (score[0] - score[1]) == (pred[0] - pred[1]):
        return 3
    if ((score[0] - score[1]) > 0) - ((score[0] - score[1]) < 0) \
            == ((pred[0] - pred[1]) > 0) - ((pred[0] - pred[1]) < 0):
        return 2
    return 0


def duel_points(pts, opp_pts) -> int:
    """Calculates the points gained by the given score"""
    try:
        pts = int(pts)
    except (ValueError, TypeError):
        return 0
    try:
        opp_pts = int(opp_pts)
    except (ValueError, TypeError):
        opp_pts = 0
    return 3 * (pts > opp_pts) + (pts == opp_pts)


def pointdiff_possible(score: Tuple[int, int], pred1, pred2):
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


def determine_winner(points_h: str, points_a: str, diff_h: int, diff_a: int) -> MatchResult:
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
    if points_a > (points_h + diff_h):
        return MatchResult.AWAY
    if points_h == points_a and diff_h == 0 and diff_a == 0:
        return MatchResult.DRAW
    return MatchResult.NONE


def convert_to_datetime(day: Union[int, str], time: Union[float, str]) -> datetime:
    """
    Converts day and time data to a datetime.

    :param day: day?
    :param time: time?
    :return: datetime??
    """
    if isinstance(day, int):
        day_ = datetime(1899, 12, 30) + timedelta(days=day)
    else:
        try:
            date = [int(x) for x in day.split(".") if x != ""]
            if len(date) < 3:
                date.append(datetime.today().year)
            day_ = datetime(*date[::-1])
        except (TypeError, ValueError):
            day_ = datetime.today()
    if isinstance(time, float):
        time_ = datetime(1, 1, 1) + timedelta(days=time)
    else:
        try:
            time_ = datetime.strptime(time, "%H:%M")
        except (TypeError, ValueError):
            time_ = datetime.now()
    return datetime.combine(day_.date(), time_.time())


def match_status(day: Union[datetime, int, str], time: Union[float, str] = None) -> MatchStatus:
    """
    Checks the status of a match (Solely time-based)

    :param day: datetime or day of kick-off
    :param time: time of kick-off
    :return: COMPLETED for finished matches, RUNNING for currently active matches (2 hours after kickoff) and UPCOMING
        for matches not started. UNKNOWN if unable to read the date or time
    """
    if isinstance(day, datetime):
        match_datetime = day
    else:
        match_datetime = convert_to_datetime(day, time)

    now = datetime.now()
    try:
        timediff = (now - match_datetime).total_seconds()
        if timediff < 0:
            return MatchStatus.UPCOMING
        if timediff < 7200:
            return MatchStatus.RUNNING
        return MatchStatus.COMPLETED
    except ValueError:
        return MatchStatus.UNKNOWN


def get_user_league(plugin, user: str) -> str:
    """
    Returns the league of the user

    :param plugin: Spaetzle plugin
    :type plugin: plugins.spaetzle.spaetzle.Plugin
    :param user: Spaetzle participant
    :return: number of the league
    :raises UserNotFound: if the user is not a valid participant
    """
    for league, participants in Storage().get(plugin)['participants'].items():
        if user.lower() in (x.lower() for x in participants):
            return league
    raise UserNotFound(user)


def get_user_cell(plugin, user: str) -> Cell:
    """
    Returns the position of the user's title cell in the 'Tipps' section

    :param plugin: Spaetzle plugin
    :type plugin: plugins.spaetzle.spaetzle.Plugin
    :param user: Spaetzle participant
    :return: users Cell
    :raises UserNotFound: if the user is not a valid participant
    """
    for league, participants in Storage().get(plugin)['participants'].items():
        for i in range(len(participants)):
            if user.lower() == participants[i].lower():
                return Cell(column=60 + (2 * i), row=12 * (int(league) - 1) + 2)
    raise UserNotFound(user)


def get_schedule(plugin, league: str, matchday: int) -> list:
    """
    Returns the duels for a given Spaetzle league and matchday

    :param plugin: Spaetzle plugin
    :type plugin: plugins.spaetzle.spaetzle.Plugin
    :param league: Spaetzle league
    :param matchday: matchday
    :return: list of duels
    :raises LeagueNotFound: if league is not valid
    """
    matchday = [2, 11, 0, 8, 6, 16, 10, 14, 15, 4, 3, 9, 12, 1, 5, 13, 7][matchday - 1]  # "Randomize" input
    participants = Storage().get(plugin)['participants'].get(league)
    if participants is None:
        raise LeagueNotFound()
    participants.extend([None] * max(0, 18 - len(participants)))  # Extend if not enough participants
    p = [participants[i] for i in [4, 2, 11, 16, 9, 17, 10, 14, 7, 3, 15, 12, 1, 0, 8, 5, 6, 13]]
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


def get_schedule_opponent(plugin, participant: str, matchday: int) -> Optional[str]:
    """
    Returns participants opponent on given matchday

    :param plugin: Spaetzle plugin
    :type plugin: plugins.spaetzle.spaetzle.Plugin
    :param participant: name of the Spaetzle participant
    :param matchday: matchday
    :return: name of the opponent
    """
    league = get_user_league(plugin, participant)
    schedule = get_schedule(plugin, league, matchday)
    for home, away in schedule:
        if home == participant:
            return away
        if away == participant:
            return home
    return None


def get_participant_history(plugin, participant: str) -> list:
    """
    Returns a summary of the completed duels

    :param plugin: Spaetzle plugin
    :type plugin: plugins.spaetzle.spaetzle.Plugin
    :param participant: name of the Spaetzle participant
    :return: (title, pts, pts_opp, opp)-tuple list
    """
    c = plugin.get_api_client()
    cell = get_user_cell(plugin, participant)
    cell_range = CellRange(start_cell=cell.translate(0, 10), width=2, height=2).rangename()
    current = Storage.get(plugin)['matchday']
    ranges = ["ST {}!{}".format(t, cell_range) for t in range((current - 1) // 17 * 17 + 1, current)]
    values = c.get_multiple(ranges=ranges)
    data = []
    for title, v in zip(range((current - 1) // 17 * 17 + 1, current), values):
        pts = v[0][0]
        pts_opp = v[1][0]
        opp = v[1][1]
        data.append((title, pts, pts_opp, opp))
    return data
