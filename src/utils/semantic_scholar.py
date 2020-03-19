from utils.http import GET, http_request


class SemanticScholar:
    """A paper in \"citations\" lists the current doi in its references section.
    A paper in \"references\" is listed in the references section of the
    current doi.
    """

    base_url = 'https://api.semanticscholar.org/v1/paper/'

    def __init__(self, doi):
        assert doi is not None, '`doi` must not be `None`'
        self.execute(doi)

    def execute(self, doi=None):
        url = self.base_url
        if doi is not None:
            url += doi
        response = http_request(GET, url)
        self.response = response
        self.data = self.response.json()
        self.references = self.data['references']
        self.referenced_by = self.data['citations']
