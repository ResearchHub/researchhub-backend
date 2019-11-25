from django.test import TestCase
from django.forms.models import model_to_dict

from paper.serializers import PaperSerializer
from paper.tests import helpers


class PaperSerializersTests(TestCase):

    def setUp(self):
        pass

    def test_authors_field_is_optional(self):
        paper = helpers.create_paper(title='Serialized Paper Title')
        paper_dict = model_to_dict(paper)
        serialized = PaperSerializer(data=paper_dict)
        self.assertTrue(serialized.is_valid())
