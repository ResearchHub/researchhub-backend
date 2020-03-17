from utils.http import GET, http_request


class SemanticScholarApi:
    """A paper in \"citations\" lists the current doi in its references section.
    A paper in \"references\" is listed in the references section of the
    current doi.
    """

    base_url = 'https://api.semanticscholar.org/v1/paper/'

    def execute(self, doi=None):
        url = self.base_url
        if doi is not None:
            url += doi
        response = http_request(GET, url)
        return response.json()

    def parse_references(self, response):
        return response['references']

    def parse_referenced_by(self, response):
        return response['citations']


semantic_scholar_api = SemanticScholarApi()
