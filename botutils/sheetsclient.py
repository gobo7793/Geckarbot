import logging
import os
import urllib.parse

from conf import Config
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
        params.append(('key', self.GOOGLE_API_KEY))
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
        return self.number_to_column(col) + str(row)

    def get(self, range, formatted: bool = True) -> list:
        """
        Reads a single range
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

    def get_multiple(self, ranges, formatted: bool = True) -> list:
        """
        Reads multiple ranges
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
        :param values: values as a matrix of cells
        :param raw: whether valueInputOption should be 'raw'
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

    def update_multiple(self, data_dict: dict):
        """
        NOT IMPLEMENTED
        Updates the content of multiple ranges

        :param data_dict: dictionary with the range as key and range values as values
        :return: response with information about the updates
        """

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
        response = self.get_service().spreadsheets().values().batchUpdate(spreadsheetId=self.spreadsheet_id, body=body)
        self.logger.debug("Response: {}".format(response))
        return response
        """
        raise NotImplemented

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
