from enum import IntEnum, IntFlag


class DscState(IntEnum):
    """DSC states"""
    NA = 0
    Voting = 1
    Sign_up = 2


class GreylistGames(IntFlag):
    """Greylist supported bot games"""
    No_Game = 0
    Bomb = 1
    Dummy = 2
    Dummy2 = 4
    ALL = Bomb | Dummy | Dummy2
