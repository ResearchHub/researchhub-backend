from django.test import TestCase

from utils.semantic_scholar import SemanticScholar


class SemanticScholarUtilsTests(TestCase):

    def setUp(self):
        pass

    def test_references(self):
        arxiv_id = '2005.00372'
        id_type = SemanticScholar.ID_TYPES['arxiv']
        ss = SemanticScholar(arxiv_id, id_type=id_type)
        import ipdb; ipdb.set_trace()
        pass
