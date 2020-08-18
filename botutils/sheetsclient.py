import logging
import os
import urllib.parse

from google.oauth2 import service_account
from googleapiclient import discovery

from conf import Storage, Config
from botutils import restclient


class NoApiKey(Exception):
    """Raisen if no Google API Key is defined"""
    pass


class Client(restclient.Client):
    """
    REST Client for Google Sheets API.
    Further infos: https://developers.google.com/sheets/api
    """

    def __init__(self, spreadsheet_id):
        """
        Creates a new REST Client for Google Sheets API using the API Key given in Geckarbot.json.
        If no API Key is given, the Client can't set up.

        :param spreadsheet_id: The ID of the spreadsheet
        """

        if not Config().GOOGLE_API_KEY:
            raise NoApiKey()

        super(Client, self).__init__("https://sheets.googleapis.com/v4/spreadsheets/")

        self.spreadsheet_id = spreadsheet_id

        self.logger = logging.getLogger(__name__)
        self.logger.debug("Building Sheets API Client for spreadsheet {}".format(self.spreadsheet_id))

        scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
                  "https://www.googleapis.com/auth/spreadsheets"]
        secret_file = os.path.join(os.getcwd(), "client_secret.json")
        credentials = service_account.Credentials.from_service_account_file(secret_file, scopes=scopes)
        self.service = discovery.build('sheets', 'v4', credentials=credentials)

    def _params_add_api_key(self, params=None):
        """
        Adds the API key to the params dictionary
        """
        if params is None:
            params = []
        params.append(('key', Config().GOOGLE_API_KEY))
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

    def get(self, range):
        """
        Reads a single range
        """
        route = "{}/values/{}".format(self.spreadsheet_id, range)
        result = self._make_request(route)
        values = result['values'] if 'values' in result else []
        return values

    def get_multiple(self, ranges):
        """
        Reads multiple ranges

        :param ranges: List of ranges
        """
        route = "{}/values:batchGet".format(self.spreadsheet_id)
        params = []
        for range in ranges:
            params.append(("ranges", range))
        value_ranges = self._make_request(route, params=params)['valueRanges']
        values = []
        for vrange in value_ranges:
            if 'values' in vrange:
                values.append(vrange['values'])
            else:
                values.append([])
        return values

    def update(self, range, values):
        """
        Updates the content of a range

        :param range: range to update
        :param values: values as a matrix of cells
        :return: number of updated cells
        """
        data = {
            'values': values
        }
        result = self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id, range=range, valueInputOption='RAW', body=data).execute()
        return result.get('updatedCells')

    def update_multiple(self, data_dict: dict):
        """
        Updates the content of multiple ranges

        :param data_dict: dictionary with the range as key and range values as values
        :return: number of total updated cells
        """
        raise NotImplemented
        # data = []
        # for range in data_dict:
        #     data.append({
        #         'range': range,
        #         'values': data_dict[range]
        #     })
        # body = {
        #     'valueInputOption': 'RAW',
        #     'data': data
        # }
        # result = self.service.spreadsheets().values().batchUpdate(spreadsheetId=self.spreadsheet_id, body=body)
        # return result
