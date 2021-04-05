from collections import namedtuple
from enum import IntEnum
from typing import Optional

pos_alphabet = {"Q": 0, "R": 1, "W": 2, "T": 3, "F": 4, "D": 5, "K": 6, "B": 7}
Activity = namedtuple("Activity", "date team_name type player_name")
TeamStanding = namedtuple("TeamStanding", "team_name wins losses record fpts")
Team = namedtuple("Team", "team_name team_abbrev team_id owner_id")
Player = namedtuple("Player", "slot_position name proTeam projected_points points")
Match = namedtuple("Match", "home_team home_score home_lineup away_team away_score away_lineup")


class FantasyState(IntEnum):
    """Fantasy states"""
    NA = 0
    SIGN_UP = 1
    PREDRAFT = 2
    PRESEASON = 3
    REGULAR = 4
    POSTSEASON = 5
    FINISHED = 6


class Platform(IntEnum):
    """Hosting platform of the fantasy league"""
    ESPN = 0
    SLEEPER = 1
    # If a platform will be added, add it to Plugin.parse_platform and
    # add it in the league submodule functions and add a new FantasyLeague subclass for it!


def parse_platform(platform_name: str = None) -> Optional[Platform]:
    """
    Parses the given platform string to class:`Platform`

    :param platform_name: The platform name
    :return: the Platform enum type or None if not supported or found
    """
    if platform_name.lower() == "espn":
        return Platform.ESPN
    if platform_name.lower() == "sleeper":
        return Platform.SLEEPER
    return None
