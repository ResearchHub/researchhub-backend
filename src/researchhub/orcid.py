from researchhub.settings import SOCIALACCOUNT_PROVIDERS
from utils.http import http_request, GET, POST

orcid = SOCIALACCOUNT_PROVIDERS['orcid']


class OrcidApi:
    def __init__(
        self,
        base_domain=orcid['BASE_DOMAIN'],
        access_token=orcid['ACCESS_TOKEN'],
        refresh_token=orcid['REFRESH_TOKEN'],
    ):
        self.base_url = f'https://pub.{base_domain}/v3.0'
        self.search_url = self.base_url + '/search'
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._build_default_headers()

    def _build_default_headers(self):
        self.headers = {
            'accept': 'application/json',
            'authorization': f'Bearer {self.access_token}'
        }

    def refetch_api_tokens(self, scope='/read-public'):
        data = {
            'client_id': orcid['CLIENT_ID'],
            'client_secret': orcid['CLIENT_SECRET'],
            'grant_type': 'client_credentials',
            'scope': scope,
        }
        response = http_request(POST, data)
        self.access_token = response.data['access_token']
        self.refresh_token = response.data['refresh_token']
        self._build_default_headers()

    def search_by_name(self, given_names, family_name):
        url = self.search_url + f'/?q="{given_names}%20{family_name}"'
        response = http_request(GET, url, headers=self.headers, timeout=2)
        return response

    def search_by_id(self, uid):
        url = self.base_url + f'/{uid}/record'
        response = http_request(GET, url, headers=self.headers, timeout=2)
        return response


orcid_api = OrcidApi()
