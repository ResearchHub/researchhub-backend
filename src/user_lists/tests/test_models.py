from django.test import TestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from user.related_models.user_model import User
from user_lists.models import List, ListItem


class ModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser")

    def test_list_string_representation(self):
        list_obj = List.objects.create(name="Reading List", created_by=self.user)
        
        self.assertEqual(str(list_obj), f"{self.user}:Reading List")

    def test_list_item_string_representation(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item = ListItem.objects.create(parent_list=list_obj, unified_document=doc, created_by=self.user)
        
        self.assertEqual(str(item), str(item.id))

    def test_list_item_unique_constraint_prevents_duplicates(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=list_obj, unified_document=doc, created_by=self.user)
        
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            ListItem.objects.create(parent_list=list_obj, unified_document=doc, created_by=self.user)
