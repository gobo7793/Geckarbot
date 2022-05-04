import re
from typing import Optional, List, Tuple, Dict

from base.data import Storage, Config
from botutils.sheetsclient import Cell, CellRange


class SpaetzleUtils:
    """
    Utility functions for spaetzle commands.
    """

    def get_participant_league(self, participant: str) -> Optional[int]:
        """
        Returns the league of a participant.

        :param participant: Name of the participant.
        :return: League number if found, None else
        """
        participants = Storage().get(self)['participants']
        for i in range(len(participants)):
            if participant in participants[i]:
                return i + 1
        return None

    def get_participant_point_cellname(self, participant: str, league: int = None) -> Optional[str]:
        """
        Gets the cell name responding to the participants points

        :param participant: name of the participant
        :param league: number of the league the participant is part of
        :return: name of the cell
        """
        if not league:
            league = self.get_participant_league(participant)
        try:
            grid = CellRange.from_a1(Config().get(self)['ranges']['points_column']).overlay_range(
                CellRange.from_a1(Config().get(self)['ranges']['league_rows'][league - 1]))
            cell = Cell(column=1, row=Storage().get(self)['participants'][league - 1].index(participant) + 1, grid=grid)
            return cell.cellname()
        except ValueError:
            return None

    @staticmethod
    def extract_predictions(matches: List[str], raw_post: str) -> Dict[str, Tuple[int, int]]:
        """
        Extracts the predictions from the raw text. Only includes found matches.

        :param matches: List of match strings
        :param raw_post: raw text
        :return: Dictionary of match and predictions
        """
        predictions: Dict[str, Tuple[int, int]] = {}
        matchesre = "|".join([re.escape(m) for m in matches])
        for line in raw_post:
            if line == "\u2022 \u2022 \u2022\r":  # Signature
                break
            result = re.search(f"(?P<match>{matchesre})\\D*(?P<goals_home>\\d+)\\s*\\D\\s*(?P<goals_away>\\d+)", line)
            if not result:
                continue
            groupdict = result.groupdict()
            predictions[groupdict['match']] = (int(groupdict['goals_home']), int(groupdict['goals_away']))
        return predictions
