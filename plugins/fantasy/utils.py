import logging
from collections import namedtuple
from enum import IntEnum


pos_alphabet = {"Q": 0, "R": 1, "W": 2, "T": 3, "F": 4, "D": 5, "K": 6, "B": 7}
Activity = namedtuple("Activity", "date team_name type player_name")
TeamStanding = namedtuple("TeamStanding", "team_name wins losses record fpts")
Team = namedtuple("Team", "team_name team_abbrev team_id owner_id")
Player = namedtuple("Player", "slot_position name proTeam projected_points points")
Match = namedtuple("Match", "home_team home_score home_lineup away_team away_score away_lineup")


class FantasyState(IntEnum):
    """Fantasy states"""
    NA = 0
    Sign_up = 1
    Predraft = 2
    Preseason = 3
    Regular = 4
    Postseason = 5
    Finished = 6


class Platform(IntEnum):
    """Hosting platform of the fantasy league"""
    ESPN = 0
    Sleeper = 1
    # If a platform will be added, add it to Plugin.parse_platform and
    # add it in the league submodule functions and add a new FantasyLeague subclass for it!
