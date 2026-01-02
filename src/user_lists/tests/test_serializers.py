from django.db.models import Count, Q
from django.test import RequestFactory
from rest_framework.request import Request
from rest_framework.test import APITestCase

from paper.models import Paper
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    PAPER,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user

from user_lists.models import List, ListItem
from user_lists.serializers import (
    ListItemSerializer,
    ListItemUnifiedDocumentSerializer,
    ListSerializer,
)


class ListSerializerTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")

    def test_list_includes_all_fields_and_item_count(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(
            parent_list=list_obj, unified_document=doc, created_by=self.user
        )

        list_obj = List.objects.annotate(
            item_count=Count("items", filter=Q(items__is_removed=False))
        ).get(pk=list_obj.pk)

        serializer = ListSerializer(list_obj)
        data = serializer.data
        
        self.assertEqual(data["name"], "My List")
        self.assertEqual(data["item_count"], 1)
        self.assertIn("id", data)
        self.assertIn("is_public", data)
        self.assertIn("created_date", data)
        self.assertIn("updated_date", data)

class ListItemSerializerTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")
        self.other_user = create_random_authenticated_user("user2")
        self.list = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.doc.created_by = self.user
        self.doc.save()
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date="2025-01-01",
            unified_document=self.doc,
            uploaded_by=self.user,
        )

    def test_list_item_includes_document_field(self):
        item = ListItem.objects.create(
            parent_list=self.list, unified_document=self.doc, created_by=self.user
        )
        serializer = ListItemSerializer(item)
        data = serializer.data

        self.assertIn("id", data)
        self.assertIn("parent_list", data)
        self.assertIn("unified_document", data)
        self.assertIn("document", data)
        self.assertIsNotNone(data["document"])
        self.assertEqual(data["document"]["content_type"], "PAPER")

    def test_item_includes_valid_document(self):
        item = ListItem.objects.create(
            parent_list=self.list, unified_document=self.doc, created_by=self.user
        )
        serializer = ListItemSerializer(item)
        self.assertIsNotNone(serializer.data["document"])
        self.assertIsNotNone(serializer.data["document"]["content_object"])
    
    def test_returns_none_when_unified_document_is_missing(self):
        from unittest.mock import Mock
        
        mock_item = Mock(spec=ListItem)
        mock_item.id = 1
        mock_item.parent_list = self.list
        mock_item.unified_document = None
        mock_item.created_by = self.user
        mock_item.updated_by = None
        mock_item.created_date = "2025-01-01"
        mock_item.updated_date = "2025-01-01"
        
        serializer = ListItemSerializer(mock_item)
        self.assertIsNone(serializer.data["document"])

    def test_user_cannot_add_to_other_users_list(self):
        factory = RequestFactory()
        request = factory.post("/api/list/")
        request.user = self.user

        other_list = List.objects.create(
            name="Other List", created_by=self.other_user
        )
        serializer = ListItemSerializer(
            data={"parent_list": other_list.id, "unified_document": self.doc.id},
            context={"request": Request(request)},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("Invalid list", str(serializer.errors))

    def test_user_cannot_add_to_removed_list(self):
        factory = RequestFactory()
        request = factory.post("/api/list/")
        request.user = self.user

        removed_list = List.objects.create(
            name="Removed List", created_by=self.user, is_removed=True
        )
        serializer = ListItemSerializer(
            data={"parent_list": removed_list.id, "unified_document": self.doc.id},
            context={"request": Request(request)},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("parent_list", serializer.errors)


class ListItemUnifiedDocumentSerializerTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.doc.created_by = self.user
        self.doc.save()
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date="2025-01-01",
            unified_document=self.doc,
            uploaded_by=self.user,
        )

    def test_paper_includes_content_author_and_metrics(self):
        thread = RhCommentThreadModel.objects.create(
            content_object=self.paper, created_by=self.user
        )
        RhCommentModel.objects.create(
            thread=thread, created_by=self.user, comment_content_json={}
        )

        serializer = ListItemUnifiedDocumentSerializer(self.doc)
        data = serializer.data

        self.assertEqual(data["content_type"], "PAPER")
        self.assertEqual(data["content_object"]["title"], "Test Paper")
        self.assertEqual(data["author"]["id"], self.user.author_profile.id)
        self.assertIn("votes", data["metrics"])
        self.assertIn("comments", data["metrics"])
        self.assertIsNotNone(data["created_date"])

    def test_post_content_type_is_correct(self):
        post_doc = ResearchhubUnifiedDocument.objects.create(document_type=DISCUSSION)
        post_doc.created_by = self.user
        post_doc.save()
        ResearchhubPost.objects.create(
            title="Test Post",
            renderable_text="Test content",
            unified_document=post_doc,
            created_by=self.user,
            document_type=DISCUSSION,
        )

        serializer = ListItemUnifiedDocumentSerializer(post_doc)
        data = serializer.data

        self.assertEqual(data["content_type"], "RESEARCHHUBPOST")
        self.assertEqual(data["content_object"]["title"], "Test Post")

    def test_unsupported_document_types_return_none(self):
        unsupported_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="QUESTION"
        )
        unsupported_doc.created_by = self.user
        unsupported_doc.save()
        
        Paper.objects.create(
            title="Question Paper",
            paper_publish_date="2025-01-01",
            unified_document=unsupported_doc,
            uploaded_by=self.user,
        )
        
        serializer = ListItemUnifiedDocumentSerializer(unsupported_doc)
        data = serializer.data
        self.assertIsNone(data["content_object"])

    def test_metrics_includes_adjusted_score(self):
        """Test adjusted_score is included in metrics."""
        serializer = ListItemUnifiedDocumentSerializer(self.doc)
        data = serializer.data

        self.assertIn("adjusted_score", data["metrics"])
        self.assertIsInstance(data["metrics"]["adjusted_score"], int)

    def test_adjusted_score_increases_with_external_engagement(self):
        """Test adjusted_score is higher when external metrics exist."""
        # Without external metrics
        serializer = ListItemUnifiedDocumentSerializer(self.doc)
        base_adjusted = serializer.data["metrics"]["adjusted_score"]

        # With external metrics
        self.paper.external_metadata = {
            "metrics": {"x": {"total_likes": 100, "total_impressions": 1000}}
        }
        self.paper.save()

        serializer = ListItemUnifiedDocumentSerializer(self.doc)
        boosted_adjusted = serializer.data["metrics"]["adjusted_score"]

        self.assertGreater(boosted_adjusted, base_adjusted)

