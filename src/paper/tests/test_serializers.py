from django.forms.models import model_to_dict
from django.test import TestCase

from hub.tests.helpers import create_hub
from paper.models import Paper, PaperVersion
from paper.serializers import PaperSerializer
from paper.tests import helpers


class PaperSerializersTests(TestCase):

    def setUp(self):
        pass

    def test_authors_field_is_optional(self):
        hub_1 = create_hub(name="Hub 1")
        hub_2 = create_hub(name="Hub 2")
        paper = helpers.create_paper(title="Serialized Paper Title")
        paper.hubs.add(hub_1)
        paper.hubs.add(hub_2)
        paper_dict = model_to_dict(paper)
        serialized = PaperSerializer(data=paper_dict)
        self.assertTrue(serialized.is_valid())

    def test_hubs_field_is_optional(self):
        paper = helpers.create_paper(title="Hubs Required")
        paper_dict = model_to_dict(paper)
        serialized = PaperSerializer(data=paper_dict)
        self.assertTrue(serialized.is_valid())

    def test_paper_serializer_paper_versions(self):
        paper = helpers.create_paper(title="Serialized Paper Title")
        PaperVersion.objects.create(paper=paper, version=1, base_doi="10.1234/test")

        serialized = PaperSerializer(paper)
        self.assertEqual(serialized.data["version"], 1)
        self.assertEqual(
            serialized.data["version_list"], [{"version": 1, "paper_id": paper.id}]
        )

        # Create another version
        paper2 = helpers.create_paper(title="Serialized Paper Title V2")
        PaperVersion.objects.create(paper=paper2, version=2, base_doi="10.1234/test")

        serialized2 = PaperSerializer(paper2)
        self.assertEqual(serialized2.data["version"], 2)
        self.assertEqual(
            serialized2.data["version_list"],
            [
                {"version": 1, "paper_id": paper.id},
                {"version": 2, "paper_id": paper2.id},
            ],
        )
