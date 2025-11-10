from django.test import TestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from user.related_models.user_model import User
from user_lists.models import List, ListItem


class ListModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")

    def test_list_displays_user_and_name_when_converted_to_string(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        self.assertEqual(str(list_obj), f"{self.user}:My List")


class ListItemModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_list_item_displays_id_when_converted_to_string(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        self.assertEqual(str(item), str(item.id))

