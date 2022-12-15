import requests

from paper.exceptions import DOINotFoundError
from utils.sentry import log_error


class Unpaywall:
    def __init__(self, timeout=10):
        self.base_url = "https://api.unpaywall.org/v2"
        self.mail_to = "hello@researchhub.com"
        self.timeout = timeout

    def search_by_doi(self, doi):
        url = f"{self.base_url}/{doi}?email={self.mail_to}"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(e)
            log_error(e)
            raise DOINotFoundError(f"No Unpaywall works found for doi: {doi}")

        return response.json()
