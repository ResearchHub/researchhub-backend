import time
from utils.http import GET, http_request


class SemanticScholar:
    """A paper in \"citations\" lists the current doi in its references section.
    A paper in \"references\" is listed in the references section of the
    current doi.
    """

    base_url = 'https://api.semanticscholar.org/v1/paper/'

    def __init__(self, doi):
        assert doi is not None, '`doi` must not be `None`'
        self.doi = doi
        self.response = None
        self.data = None
        self.references = []
        self.referenced_by = []
        self.hub_candidates = []
        self.abstract = None
        self.execute(self.doi)

    def execute(self, doi):
        url = self.base_url
        if doi is not None:
            url += doi
        try:
            response = http_request(GET, url)
            if response.status_code == 429:
                time.sleep(10.0)
                response = http_request(GET, url)
            self.response = response
            self.data = self.response.json()
            self.references = self.data.get('references', [])
            self.referenced_by = self.data.get('citations', [])
            self.hub_candidates = self.data.get('fieldsOfStudy', [])
            self.abstract = self.data.get('abstract', None)
        except Exception as e:
            print(e)
