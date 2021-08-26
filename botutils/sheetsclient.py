import logging
import os
import re
import urllib.parse
from typing import Optional, Dict, Tuple, Union, List

from botutils import restclient
from base import NotLoadable


class NoApiKey(NotLoadable):
    """Raisen if no Google API Key is defined"""
    pass


class NoCredentials(NotLoadable):
    """Raisen if credentials for the service account are not valid"""
    pass


class Cell:
    """
    Representation of a sheet cell
    """
    def __init__(self, column: int, row: int, grid=None):
        """
        Representation of a single cell. Note: rows and columns in a grid begin at 1!

        :param column: column coordinate
        :param row: row coordinate
        :param grid: CellRange the cell coordinates are dependent on
        :type grid: CellRange
        """

        self.column = column
        self.row = row
        self.grid = grid

    @classmethod
    def from_a1(cls, a1_notation: str):
        """
        Building the cell from the A1-notation.

        :param a1_notation: A1-notation of the cell e.g. "A4" or "BE34"
        """
        extract = re.search("(?P<col>[A-Z]+)(?P<row>\\d+)", a1_notation)
        if extract:
            groupdict = extract.groupdict()
            # Converts the column title into the corresponding column number
            column = sum((x*y for x, y in zip([26**i for i in range(len(groupdict['col']))][::-1],
                                              (ord(b) - 64 for b in groupdict['col']))))
            return cls(column, int(groupdict['row']))
        raise ValueError

    def cellname(self) -> str:
        """Returns cell in A1-notation"""
        chars = []
        num = self.column
        if self.grid:
            num += self.grid.column - 1
        while num > 0:
            num, d = divmod(num, 26)
            if d == 0:
                num, d = num - 1, 26
            chars.append(chr(64 + d))
        row_num = self.row
        if self.grid:
            row_num += self.grid.row - 1
        return ''.join(reversed(chars)) + str(row_num)

    def translate(self, columns: int, rows: int):
        """
        Returns cell translated by the given number of columns and rows

        :param columns: number of columns the cell should be moved
        :param rows: number of rows the rows the cell should be moved
        :return: resulting cell
        """
        return Cell(column=self.column + columns,
                    row=self.row + rows,
                    grid=self.grid)


class CellRange:
    """
    Represents a range of cells
    """
    def __init__(self, start_cell: Cell, width: int, height: int):
        """
        Representation of a range of cells. Note: rows and columns in a grid begin at 1!

        :param start_cell: top-left Cell
        :param width: number of columns
        :param height: number of rows
        """
        self.column = start_cell.column
        self.row = start_cell.row
        self.width = width
        self.height = height

    @classmethod
    def from_a1(cls, a1_notation: str):
        """
        Builds a CellRange object from "A1:B4" notation

        :param a1_notation: notation string
        :return: Corresponding CellRange object
        """
        extract = re.search("(?P<cell1>[A-Z]+\\d+):(?P<cell2>[A-Z]+\\d+)", a1_notation)
        if extract:
            groupdict = extract.groupdict()
            return cls.from_cells(Cell.from_a1(groupdict['cell1']), Cell.from_a1(groupdict['cell2']))
        raise ValueError

    @classmethod
    def from_cells(cls, start_cell: Cell, end_cell: Cell):
        """
        Builds a CellRange object by passing two corners of the range rectangle.

        :param start_cell: top left
        :param end_cell: bottom right
        :return: Corresponding CellRange object
        """
        width = end_cell.column - start_cell.column + 1
        height = end_cell.row - start_cell.row + 1
        return cls(start_cell, width, height)

    def rangename(self):
        """Returns cell range in A1-notation"""
        return "{}:{}".format(Cell(self.column, self.row).cellname(),
                              Cell(self.column + self.width - 1, self.row + self.height - 1).cellname())

    def translate(self, columns: int, rows: int):
        """
        Returns cell range translated by the given number of columns and rows

        :param columns: number of columns the range should be moved
        :param rows: number of rows the rows the range should be moved
        :return: resulting cell range
        """
        return CellRange(start_cell=Cell(column=self.column + columns,
                                         row=self.row + rows),
                         width=self.width,
                         height=self.height)

    def expand(self, top: int = 0, bottom: int = 0, left: int = 0, right: int = 0):
        """
        Returns cell range expanded by the given amount in each direction
        """
        if self.column <= left or self.row <= top or left + right <= -self.width or top + bottom <= -self.height:
            raise ValueError
        return CellRange(start_cell=Cell(column=self.column - left, row=self.row - top),
                         width=self.width + left + right,
                         height=self.height + top + bottom)


def get_service():
    """Returns the service for the google sheets"""
    # pylint: disable=import-outside-toplevel
    try:
        from google.oauth2 import service_account
        from googleapiclient import discovery
        scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
                  "https://www.googleapis.com/auth/spreadsheets"]
        secret_file = os.path.join(os.getcwd(), "config/google_service_account.json")
        credentials = service_account.Credentials.from_service_account_file(secret_file, scopes=scopes)
        service = discovery.build('sheets', 'v4', credentials=credentials)
    except ImportError as e:
        raise NotLoadable("Google API modules not installed.") from e
    except Exception as e:
        raise NoCredentials() from e
    else:
        return service


class Client(restclient.Client):
    """
    REST Client for Google Sheets API.
    Further infos: https://developers.google.com/sheets/api
    """

    def __init__(self, bot, spreadsheet_id: int):
        """
        Creates a new REST Client for Google Sheets API using the API Key given in Geckarbot.json.
        If no API Key is given, the Client can't set up.

        :param bot: Geckarbot reference
        :param spreadsheet_id: The ID of the spreadsheet
        """

        super().__init__("https://sheets.googleapis.com/v4/spreadsheets/")

        self.bot = bot
        self.spreadsheet_id = spreadsheet_id

        self.logger = logging.getLogger(__name__)
        self.logger.debug("Building Sheets API Client for spreadsheet %s", self.spreadsheet_id)

    def _params_add_api_key(self, params=None):
        """
        Adds the API key to the params dictionary

        :raises NoApiKey: If the Google API key is not set
        """
        if not self.bot.GOOGLE_API_KEY:
            raise NoApiKey()
        if params is None:
            params = []
        params.append(('key', self.bot.GOOGLE_API_KEY))
        return params

    def _make_request(self, route: str, params=None):
        """
        Makes a Sheets Request
        """
        route = urllib.parse.quote(route, safe="/:")
        params = self._params_add_api_key(params)
        # self.logger.debug("Making Sheets request {}, params: {}".format(route, params))
        response = self.make_request(route, params=params)
        # self.logger.debug("Response: {}".format(response))
        return response

    def _get_sheets(self):
        """
        Gets all sheets

        :return: List of sheets
        """
        info = get_service().spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        sheets = info.get('sheets', [])
        return sheets

    def _get_sheet_properties(self, sheet: str):
        """
        Returns properties of the specified sheet

        :param sheet: name or id of the sheet
        :return: sheet properties
        """
        sheets = self._get_sheets()
        for sh in sheets:
            properties = sh.get('properties', {})
            if sheet == properties.get('title') or sheet == properties.get('sheetId'):
                return properties
        return None

    def _get_sheet_id(self, sheet: Union[int, str]):
        """
        Converts the title of a sheet into the coresponding sheet id

        :return: sheet id
        """
        if isinstance(sheet, int):
            return sheet
        return self._get_sheet_properties(sheet).get('sheetId')

    def get(self, cellrange: str, formatted: bool = True) -> List[List[str]]:
        """
        Reads a single range

        :param cellrange: rangename
        :param formatted: whether the cell values should be read formatted/as seen in the sheet or not
        :return: values of that range
        """
        value_render_option = "FORMATTED_VALUE" if formatted else "UNFORMATTED_VALUE"
        if self.bot.GOOGLE_API_KEY:
            route = "{}/values/{}".format(self.spreadsheet_id, cellrange)
            response = self._make_request(route, params=[('valueRenderOption', value_render_option)])
        else:
            response = get_service().spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id, range=cellrange, valueRenderOption=value_render_option).execute()
            self.logger.debug("Response: %s", response)

        values = response.get('values', [])
        return values

    def get_multiple(self, ranges: List[str], formatted: bool = True) -> List[List[List[str]]]:
        """
        Reads multiple ranges

        :param ranges: list of ranges
        :param formatted: whether the cell values should be read formatted/as seen in the sheet or not
        :return: values list
        """
        value_render_option = "FORMATTED_VALUE" if formatted else "UNFORMATTED_VALUE"
        if self.bot.GOOGLE_API_KEY:
            route = "{}/values:batchGet".format(self.spreadsheet_id)
            params = [('valueRenderOption', value_render_option)]
            for cellrange in ranges:
                params.append(("ranges", cellrange))
            response = self._make_request(route, params=params)
        else:
            response = get_service().spreadsheets().values().batchGet(
                spreadsheetId=self.spreadsheet_id, ranges=ranges, valueRenderOption=value_render_option).execute()
            self.logger.debug("Response: %s", response)

        value_ranges = response.get('valueRanges', [])
        values = []
        for vrange in value_ranges:
            values.append(vrange.get('values', []))
        return values

    def update(self, cellrange: str, values: List[List[str]], raw: bool = True) -> Dict:
        """
        Updates the content of a range

        :param cellrange: range to update
        :param values: values as a matrix of cells [[cells...], rows...]
        :param raw: if True, values are put in 'raw', if False as 'user_entered'
        :return: UpdateValuesResponse
        """
        data = {
            'values': values
        }
        value_input_option = 'RAW' if raw else 'USER_ENTERED'
        response = get_service().spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id, range=cellrange,
            valueInputOption=value_input_option, body=data).execute()
        self.logger.debug("Response: %s", response)
        return response

    def update_multiple(self, data_dict: dict, raw: bool = True) -> Dict:
        """
        Updates the content of multiple ranges

        :param raw: if True, values are put in 'raw', if False as 'user_entered'
        :param data_dict: dictionary with the range as key and range values as matrixes of values
                          (as following: [[cells..], rows..])
        :return: response with information about the updates
        """

        data = []
        for range in data_dict:
            data.append({
                'range': range,
                'values': data_dict[range]
            })
        value_input_option = 'RAW' if raw else 'USER_ENTERED'
        body = {
            'valueInputOption': value_input_option,
            'data': data
        }
        response = get_service().spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body).execute()
        self.logger.debug("Response: %s", response)
        return response

    def append(self, cellrange: str, values, raw: bool = True) -> Dict:
        """
        Appends values to a table (Warning: can maybe overwrite cells below the table)

        :param cellrange: range to update
        :param values: values as a matrix of cells
        :param raw: whether valueInputOption should be 'raw'
        :return: UpdateValuesResponse
        """
        data = {
            'values': values
        }
        value_input_option = 'RAW' if raw else 'USER_ENTERED'
        response = get_service().spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=cellrange, valueInputOption=value_input_option,
            body=data).execute()
        self.logger.debug("Response: %s", response)
        return response.get('updates', {})

    def clear(self, cellrange: str) -> Dict:
        """
        Clears a range

        :param cellrange: range to be cleared
        :return: response
        """
        response = get_service().spreadsheets().values().clear(
            spreadsheetId=self.spreadsheet_id, range=cellrange).execute()
        return response

    def clear_multiple(self, ranges: List[str]) -> Dict:
        """
        Clears multiple ranges

        :param ranges: list of ranges
        :return: response
        """
        body = {
            'ranges': ranges
        }
        response = get_service().spreadsheets().values().batchClear(
            spreadsheetId=self.spreadsheet_id, body=body).execute()
        return response

    def add_sheet(self, title: str, rows: int = 1000, columns: int = 26) -> Optional[Dict]:
        """
        Adds a new sheet

        :param title: name of the new sheet
        :param rows: number of rows
        :param columns: number of columns
        :return: AddSheetResponse if successful, None instead
        :raises NotLoadable: If Google API packages are not installed
        """
        # pylint: disable=import-outside-toplevel
        body = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": title,
                            "gridProperties": {
                                "rowCount": rows,
                                "columnCount": columns,
                            }
                        }
                    }
                }
            ]
        }
        try:
            from googleapiclient.errors import HttpError
            try:
                response = get_service().spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id,
                                                                    body=body).execute()
                return response
            except HttpError:
                return None
        except ImportError as e:
            raise NotLoadable("Google API modules not installed.") from e

    def duplicate_sheet(self, sheet: Union[str, int], new_title: str = None, index: int = None,
                        new_id: int = None) -> Optional[Dict]:
        """
        Duplicates a sheet

        :param new_id: id of the resulting duplicate
        :param index: The zero-based index where the new sheet should be inserted. The index of all sheets after this
                      are incremented.
        :param sheet: name or id of the sheet
        :param new_title: title of the resulting duplicate
        :return: DuplicateSheetResponse if successful, None instead
        :raises NotLoadable: If google API packages are not installed
        """
        # pylint: disable=import-outside-toplevel
        properties = self._get_sheet_properties(sheet)
        if properties is None:
            return None
        if isinstance(sheet, int):
            sheet_id = sheet
        else:
            sheet_id = properties.get('sheetId')

        request = {
            "sourceSheetId": sheet_id,
            "insertSheetIndex": index if index is not None else properties.get('index') + 1
        }
        if new_title:
            request['newSheetName'] = new_title
        if new_id:
            request['newSheetId'] = new_id
        body = {
            "requests": [{
                "duplicateSheet": request
            }]
        }
        try:
            from googleapiclient.errors import HttpError
            try:
                response = get_service().spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id, body=body).execute()
                return response
            except HttpError:
                return None
        except ImportError as e:
            raise NotLoadable("Google API modules not installed.") from e

    def duplicate_and_archive_sheet(self, sheet: str, new_title: str = None, index: int = None,
                                    new_id: int = None) -> Optional[Tuple[Dict, Dict]]:
        """
        Duplicates a sheet and transforms the duplicate to raw input

        :param new_id: id of the resulting duplicate
        :param index: The zero-based index where the new sheet should be inserted. The index of all sheets after this
                      are incremented.
        :param sheet: name or id of the sheet
        :param new_title: title of the resulting duplicate
        :return: DuplicateSheetResponse and UpdateValuesResponse if successful, None instead
        """
        # Duplicate
        duplicate = self.duplicate_sheet(sheet=sheet, new_title=new_title, index=index, new_id=new_id)
        if duplicate is None:
            return None
        # Get content
        properties = duplicate.get('replies', [{}])[0].get('duplicateSheet', {}).get('properties', {})
        cellrange = "{}!A1:{}".format(properties.get('title'),
                                      Cell(properties.get('gridProperties', {}).get('columnCount'),
                                           properties.get('gridProperties', {}).get('rowCount')).cellname())
        values = self.get(cellrange, formatted=True)
        # Insert raw again
        response = self.update(cellrange, values, raw=True)
        return duplicate, response

    def find_and_replace(self, find: str, replace: str, match_case: bool = True, match_entire_cell: bool = False,
                         search_by_regex: bool = False, include_formulas: bool = False, cellrange: str = None,
                         sheet: str = None, all_sheets: bool = False) -> Optional[Dict]:
        """
        Find a string and replace by another. Scope to find/replace over can be set in 3 different ways:
        all_sheets / sheet / range + sheet

        :param find: the value to search
        :param replace: the value to use as the replacement
        :param match_case: True if the search is case sensitive
        :param match_entire_cell: True if the find value should match the entire cell
        :param search_by_regex: True if the find value is a regex
        :param include_formulas: True if the search should include cells with formulas. False to skip cells with
                                 formulas
        :param cellrange: The range to find/replace over. Use sheet for the sheet id/name.
        :param sheet: The sheet to find/replace over.
        :param all_sheets: True to find/replace over all sheets. Overwrites range and sheet
        :raises NotLoadable: if Google API modules not installed
        :return: FindReplaceResponse
        """
        # pylint: disable=import-outside-toplevel
        request = {
            "find": find,
            "replacement": replace,
            "matchCase": match_case,
            "matchEntireCell": match_entire_cell,
            "searchByRegex": search_by_regex,
            "includeFormulas": include_formulas
        }
        if all_sheets:
            request['allSheets'] = True
        elif sheet and cellrange:
            sheet_id = self._get_sheet_id(sheet)
            if sheet_id:
                try:
                    cell_range = CellRange.from_a1(cellrange)
                except ValueError:
                    return None
                else:
                    request['range'] = {
                        "sheetId": sheet_id,
                        "startRowIndex": cell_range.row,
                        "endRowIndex": cell_range.row + cell_range.height,
                        "startColumnIndex": cell_range.column,
                        "endColumnIndex": cell_range.column + cell_range.width
                    }
            else:
                return None
        elif sheet:
            sheet_id = self._get_sheet_id(sheet)
            if sheet_id:
                request['sheetId'] = sheet_id
            else:
                return None
        else:
            return None
        body = {
            "requests": [{
                "findReplace": request
            }]
        }
        try:
            from googleapiclient.errors import HttpError
            try:
                response = get_service().spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id, body=body).execute()
                return response
            except HttpError:
                return None
        except ImportError as e:
            raise NotLoadable("Google API modules not installed.") from e
