import requests

from paper.exceptions import DOINotFoundError


class SemanticScholar:
    def __init__(self, timeout=10):
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.base_headers = {
            "User-Agent": "mailto:hello@researchhub.com",
            "From": "mailto:hello@researchhub.com",
        }
        self.base_fields = ",".join(
            (
                "authors",
                "url",
                "title",
                "abstract",
                "isOpenAccess",
                "journal",
                "tldr",
                "publicationDate",
            )
        )
        self.timeout = timeout

    def _get_paper(self, identifier, fields=None):
        if not fields:
            params = {"fields": self.base_fields}
        else:
            params = {"fields": fields}

        url = f"{self.base_url}/paper/{identifier}"

        try:
            response = requests.get(
                url, headers=self.base_headers, params=params, timeout=self.timeout
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            raise DOINotFoundError(e)

        return response.json()

    def get_data_from_doi(self, doi):
        identifier = f"DOI:{doi}"
        response = self._get_paper(identifier)
        return response

    def get_data_from_url(self, url):
        identifier = f"URL:{url}"
        response = self._get_paper(identifier)
        return response


"""
from utils.semantic_scholar import SemanticScholar
ss = SemanticScholar()
ss.get_paper_from_doi("10.2139/ssrn.3039505")
"""
