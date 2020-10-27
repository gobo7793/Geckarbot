import logging
import os
import urllib.parse

from botutils import restclient
from base import NotLoadable


class NoApiKey(NotLoadable):
    """Raisen if no Google API Key is defined"""
    pass


class NoCredentials(NotLoadable):
    """Raisen if credentials for the service account are not valid"""
    pass


class Client(restclient.Client):
    """
    REST Client for Google Sheets API.
    Further infos: https://developers.google.com/sheets/api
    """

    def __init__(self, bot, spreadsheet_id):
        """
        Creates a new REST Client for Google Sheets API using the API Key given in Geckarbot.json.
        If no API Key is given, the Client can't set up.

        :param bot: Geckarbot reference
        :param spreadsheet_id: The ID of the spreadsheet
        """

        super(Client, self).__init__("https://sheets.googleapis.com/v4/spreadsheets/")

        self.bot = bot
        self.spreadsheet_id = spreadsheet_id

        self.logger = logging.getLogger(__name__)
        self.logger.debug("Building Sheets API Client for spreadsheet {}".format(self.spreadsheet_id))

    def get_service(self):
        try:
            from google.oauth2 import service_account
            from googleapiclient import discovery
            scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
                      "https://www.googleapis.com/auth/spreadsheets"]
            secret_file = os.path.join(os.getcwd(), "config/google_service_account.json")
            credentials = service_account.Credentials.from_service_account_file(secret_file, scopes=scopes)
            service = discovery.build('sheets', 'v4', credentials=credentials)
        except ImportError:
            raise NotLoadable("Google API modules not installed.")
        except Exception:
            raise NoCredentials()
        else:
            return service

    def _params_add_api_key(self, params=None):
        """
        Adds the API key to the params dictionary
        """
        if not self.bot.GOOGLE_API_KEY:
            raise NoApiKey()
        if params is None:
            params = []
        params.append(('key', self.bot.GOOGLE_API_KEY))
        return params

    def _make_request(self, route, params=None):
        """
        Makes a Sheets Request
        """
        route = urllib.parse.quote(route, safe="/:")
        params = self._params_add_api_key(params)
        # self.logger.debug("Making Sheets request {}, params: {}".format(route, params))
        response = self.make_request(route, params=params)
        # self.logger.debug("Response: {}".format(response))
        return response

    def get_sheet_properties(self, sheet):
        """
        Converts the title of a sheet into the coresponding sheet id

        :param sheet: name or id of the sheet
        :return: sheetId if found, None instead
        """
        info = self.get_service().spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        for sh in info.get('sheets', []):
            properties = sh.get('properties', {})
            if sheet == properties.get('title') or sheet == properties.get('sheetId'):
                return properties

    def number_to_column(self, num):
        """
        Converts a number to the name of the corresponding column
        """
        chars = []
        while num > 0:
            num, d = divmod(num, 26)
            if d == 0:
                num, d = num - 1, 26
            chars.append(chr(64 + d))
        return ''.join(reversed(chars))

    def cellname(self, col, row):
        """
        Returns the name of the cell
        """
        if col and row:
            return self.number_to_column(col) + str(row)
        else:
            return None

    def get(self, range, formatted: bool = True) -> list:
        """
        Reads a single range
        :param range:
        :param formatted:
        :return:
        """
        value_render_option = "FORMATTED_VALUE" if formatted else "UNFORMATTED_VALUE"
        if self.bot.GOOGLE_API_KEY:
            route = "{}/values/{}".format(self.spreadsheet_id, range)
            response = self._make_request(route, params=[('valueRenderOption', value_render_option)])
        else:
            response = self.get_service().spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id, range=range, valueRenderOption=value_render_option).execute()
            self.logger.debug("Response: {}".format(response))

        values = response.get('values', [])
        return values

    def get_multiple(self, ranges: list, formatted: bool = True) -> list:
        """
        Reads multiple ranges

        :param ranges: list of ranges
        :param formatted: whether the cell values should be read formatted (True) or unformatted (False)
        :return: values list
        """
        value_render_option = "FORMATTED_VALUE" if formatted else "UNFORMATTED_VALUE"
        if self.bot.GOOGLE_API_KEY:
            route = "{}/values:batchGet".format(self.spreadsheet_id)
            params = [('valueRenderOption', value_render_option)]
            for range in ranges:
                params.append(("ranges", range))
            response = self._make_request(route, params=params)
        else:
            response = self.get_service().spreadsheets().values().batchGet(
                spreadsheetId=self.spreadsheet_id, ranges=ranges, valueRenderOption=value_render_option).execute()
            self.logger.debug("Response: {}".format(response))

        value_ranges = response.get('valueRanges', [])
        values = []
        for vrange in value_ranges:
            values.append(vrange.get('values', []))
        return values

    def update(self, range, values, raw: bool = True) -> dict:
        """
        Updates the content of a range

        :param range: range to update
        :param values: values as a matrix of cells [[cells...], rows...]
        :param raw: if True, values are put in 'raw', if False as 'user_entered'
        :return: UpdateValuesResponse
        """
        data = {
            'values': values
        }
        value_input_option = 'RAW' if raw else 'USER_ENTERED'
        response = self.get_service().spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id, range=range, valueInputOption=value_input_option, body=data).execute()
        self.logger.debug("Response: {}".format(response))
        return response

    def update_multiple(self, data_dict: dict, raw: bool = True) -> dict:
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
        body = {
            'valueInputOption': 'RAW',
            'data': data
        }
        value_input_option = 'RAW' if raw else 'USER_ENTERED'
        response = self.get_service().spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body, valueInputOption=value_input_option).execute()
        self.logger.debug("Response: {}".format(response))
        return response

    def append(self, range, values, raw: bool = True) -> dict:
        """
        Appends values to a table (Warning: can maybe overwrite cells below the table)

        :param range: range to update
        :param values: values as a matrix of cells
        :param raw: whether valueInputOption should be 'raw'
        :return: UpdateValuesResponse
        """
        data = {
            'values': values
        }
        value_input_option = 'RAW' if raw else 'USER_ENTERED'
        response = self.get_service().spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=range, valueInputOption=value_input_option, body=data).execute()
        self.logger.debug("Response: {}".format(response))
        return response.get('updates', {})

    def clear(self, range) -> dict:
        """
        Clears a range
        :param range: range to be cleared
        :return: response
        """
        response = self.get_service().spreadsheets().values().clear(
            spreadsheetId=self.spreadsheet_id, range=range).execute()
        return response

    def clear_multiple(self, ranges: list) -> dict:
        """
        Clears multiple ranges
        :param ranges: list of ranges
        :return: response
        """
        body = {
            'ranges': ranges
        }
        response = self.get_service().spreadsheets().values().batchClear(
            spreadsheetId=self.spreadsheet_id, body=body).execute()
        return response

    def add_sheet(self, title: str, rows: int = 1000, columns: int = 26):
        """
        Adds a new sheet
        :param title: name of the new sheet
        :param rows: number of rows
        :param columns: number of columns
        :return: AddSheetResponse if successful, None instead
        """
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
                response = self.get_service().spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id,
                                                                         body=body).execute()
                return response
            except HttpError:
                return None
        except ImportError:
            raise NotLoadable("Google API modules not installed.")

    def duplicate_sheet(self, sheet, new_title: str = None, index: int = None, new_id: int = None):
        """
        Duplicates a sheet

        :param new_id: id of the resulting duplicate
        :param index: The zero-based index where the new sheet should be inserted. The index of all sheets after this
                      are incremented.
        :param sheet: name or id of the sheet
        :param new_title: title of the resulting duplicate
        :return: DuplicateSheetResponse if successful, None instead
        """
        properties = self.get_sheet_properties(sheet)
        if properties is None:
            return None
        if type(sheet) == int:
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
                response = self.get_service().spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id, body=body).execute()
                return response
            except HttpError:
                return None
        except ImportError:
            raise NotLoadable("Google API modules not installed.")

    def duplicate_and_archive_sheet(self, sheet, new_title: str = None, index: int = None, new_id: int = None):
        # Duplicate
        duplicate = self.duplicate_sheet(sheet=sheet, new_title=new_title, index=index, new_id=new_id)
        if duplicate is None:
            return None
        # Get content
        properties = duplicate.get('replies', [{}])[0].get('duplicateSheet', {}).get('properties', {})
        range = "{}!A1:{}".format(properties.get('title'),
                                  self.cellname(properties.get('gridProperties', {}).get('rowCount'),
                                                properties.get('gridProperties', {}).get('columnCount')))
        values = self.get(range, formatted=True)
        # Insert raw again
        response = self.update(range, values, raw=True)
        return duplicate, response