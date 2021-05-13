from django.test import TestCase
from django.forms.models import model_to_dict

from hub.tests.helpers import create_hub
from paper.serializers import PaperSerializer
from paper.tests import helpers


class PaperSerializersTests(TestCase):

    def setUp(self):
        pass

    def test_authors_field_is_optional(self):
        hub_1 = create_hub(name='Hub 1')
        hub_2 = create_hub(name='Hub 2')
        paper = helpers.create_paper(title='Serialized Paper Title')
        paper.hubs.add(hub_1)
        paper.hubs.add(hub_2)
        paper_dict = model_to_dict(paper)
        serialized = PaperSerializer(data=paper_dict)
        self.assertTrue(serialized.is_valid())

    def test_hubs_field_is_optional(self):
        paper = helpers.create_paper(title='Hubs Required')
        paper_dict = model_to_dict(paper)
        serialized = PaperSerializer(data=paper_dict)
        self.assertTrue(serialized.is_valid())
