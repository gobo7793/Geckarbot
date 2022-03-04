from typing import Optional

from base.data import Storage, Config
from botutils.sheetsclient import Cell, CellRange


class SpaetzleUtils:

    def __init__(self, bot):
        self.bot = bot

    def get_participant_league(self, participant: str) -> Optional[int]:
        """
        Returns the league of a participant.

        :param participant: Name of the participant.
        :return: League number if found, None else
        """
        participants = Storage().get(self)['participants']
        for i in range(4):
            if participant in participants[i]:
                return i + 1
        return None

    def get_participant_point_cell(self, participant: str, league: int = None) -> Optional[str]:
        if not league:
            league = self.get_participant_league(participant)
        try:
            grid = CellRange.from_a1(Config().get(self)['ranges']['points_column']).overlay_range(
                CellRange.from_a1(Config().get(self)['ranges']['league_rows'][league - 1]))
            cell = Cell(column=1, row=Storage().get(self)['participants'][league - 1].index(participant) + 1, grid=grid)
            return cell.cellname()
        except ValueError:
            return None