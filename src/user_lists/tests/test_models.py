from django.test import TestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user

from user_lists.models import List, ListItem


class ListModelTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")

    def test_list_string_representation_shows_user_and_name(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        self.assertEqual(str(list_obj), f"{self.user}:My List")


class ListItemModelTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_list_item_string_representation_shows_item_id(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        self.assertEqual(str(item), str(item.id))
