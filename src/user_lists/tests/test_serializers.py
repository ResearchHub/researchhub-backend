from unittest.mock import patch, PropertyMock

from django.test import TestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user

from user_lists.models import List, ListItem
from user_lists.serializers import ListItemDetailSerializer


class ListItemDetailSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_getting_unified_document_data_returns_serialized_data(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        serializer = ListItemDetailSerializer(item, context={"request": None})
        data = serializer.data
        self.assertIn("unified_document_data", data)
        self.assertIsInstance(data["unified_document_data"], dict)
        self.assertIn("id", data["unified_document_data"])

    def test_getting_unified_document_data_with_exception_returns_fallback_data(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        with patch("user_lists.serializers.DynamicUnifiedDocumentSerializer") as mock_serializer_class:
            mock_serializer = mock_serializer_class.return_value
            type(mock_serializer).data = PropertyMock(side_effect=Exception("Error"))
            serializer = ListItemDetailSerializer(item, context={"request": None})
            data = serializer.data
            self.assertIn("unified_document_data", data)
            unified_doc_data = data["unified_document_data"]
            self.assertEqual(unified_doc_data["id"], self.doc.id)
            self.assertEqual(unified_doc_data["document_type"], self.doc.document_type)
            self.assertEqual(unified_doc_data["is_removed"], self.doc.is_removed)
