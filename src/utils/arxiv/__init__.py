import arxiv


class Arxiv:
    def __init__(self, id=None, query=None):
        # TODO: Handle query case
        self.id = id
        self.data = None
        self._handle_doi(self.id)

    def _handle_doi(self, id):
        self.data = arxiv.query(id_list=[id])
