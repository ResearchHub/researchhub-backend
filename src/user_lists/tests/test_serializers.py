from django.test import TestCase
from django.contrib.contenttypes.models import ContentType

from paper.models import Paper
from purchase.models import Fundraise, Grant
from researchhub_document.related_models.constants.document_type import PAPER, DISCUSSION
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from researchhub_document.models import ResearchhubPost
from review.models import Review
from researchhub_comment.models import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import RhCommentThreadModel
from user.related_models.user_model import User
from user_lists.models import List, ListItem
from user_lists.serializers import (
    ListDetailSerializer,
    ListItemDetailSerializer,
    ListSerializer,
    SimpleUserForListSerializer,
    UnifiedDocumentForListSerializer,
    UserListOverviewSerializer,
    OverviewResponseSerializer,
)


class ListItemDetailSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_list_item_detail_serializer_includes_unified_document_data(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        serializer = ListItemDetailSerializer(item)
        data = serializer.data
        self.assertIn("unified_document", data)
        self.assertIsInstance(data["unified_document"], dict)
        self.assertIn("id", data["unified_document"])

    def test_list_item_detail_serializer_returns_minimal_data_when_serialization_fails(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        self.doc.delete()
        serializer = ListItemDetailSerializer(item)
        data = serializer.data
        unified_doc_data = data.get("unified_document", {})
        self.assertIsInstance(unified_doc_data, dict)
        self.assertEqual(len(unified_doc_data), 3)
        self.assertIn("id", unified_doc_data)
        self.assertEqual(unified_doc_data["id"], self.doc.id)
        self.assertIn("document_type", unified_doc_data)
        self.assertEqual(unified_doc_data["document_type"], self.doc.document_type)
        self.assertIn("is_removed", unified_doc_data)
        self.assertEqual(unified_doc_data["is_removed"], self.doc.is_removed)


class ListSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)

    def test_list_serializer_counts_only_active_items(self):
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item1 = ListItem.objects.create(parent_list=self.list_obj, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc2, created_by=self.user)
        item1.delete()
        
        serializer = ListSerializer(self.list_obj)
        self.assertEqual(serializer.get_items_count(self.list_obj), 1)

    def test_list_serializer_uses_prefetched_data(self):
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc2, created_by=self.user)
        
        list_obj_prefetched = List.objects.prefetch_related("items").get(id=self.list_obj.id)
        serializer = ListSerializer(list_obj_prefetched)
        
        self.assertTrue(hasattr(list_obj_prefetched, '_prefetched_objects_cache'))
        self.assertIn('items', list_obj_prefetched._prefetched_objects_cache)
        self.assertEqual(serializer.get_items_count(list_obj_prefetched), 2)


class ListDetailSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)

    def test_list_detail_serializer_returns_paginated_items(self):
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc2, created_by=self.user)
        
        serializer = ListDetailSerializer(self.list_obj)
        items = serializer.get_items(self.list_obj)
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0)


class UnifiedDocumentForListSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.doc = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
        ).unified_document

    def test_unified_document_serializer_includes_all_fields(self):
        serializer = UnifiedDocumentForListSerializer(self.doc)
        data = serializer.data
        
        self.assertIn("id", data)
        self.assertIn("created_date", data)
        self.assertIn("title", data)
        self.assertIn("slug", data)
        self.assertIn("is_removed", data)
        self.assertIn("document_type", data)
        self.assertIn("hubs", data)
        self.assertIn("created_by", data)
        self.assertIn("documents", data)
        self.assertIn("score", data)
        self.assertIn("hot_score", data)
        self.assertIn("reviews", data)
        self.assertIn("fundraise", data)
        self.assertIn("grant", data)

    def test_get_hubs_returns_list_with_id_name_slug(self):
        serializer = UnifiedDocumentForListSerializer(self.doc)
        hubs = serializer.get_hubs(self.doc)
        
        self.assertIsInstance(hubs, list)

    def test_get_created_by_returns_user_data(self):
        serializer = UnifiedDocumentForListSerializer(self.doc)
        created_by = serializer.get_created_by(self.doc)
        
        self.assertIsNotNone(created_by)
        self.assertIn("id", created_by)
        self.assertIn("first_name", created_by)
        self.assertIn("last_name", created_by)

    def test_get_created_by_returns_none_when_no_creator(self):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        Paper.objects.create(
            title="Test Paper",
            uploaded_by=None,
            unified_document=unified_doc,
        )
        serializer = UnifiedDocumentForListSerializer(unified_doc)
        created_by = serializer.get_created_by(unified_doc)
        
        self.assertIsNone(created_by)

    def test_get_reviews_returns_default_when_no_reviews(self):
        serializer = UnifiedDocumentForListSerializer(self.doc)
        reviews = serializer.get_reviews(self.doc)
        
        self.assertIsInstance(reviews, dict)
        self.assertEqual(reviews["avg"], 0.0)
        self.assertEqual(reviews["count"], 0)

    def test_get_fundraise_returns_none_when_no_fundraise(self):
        serializer = UnifiedDocumentForListSerializer(self.doc)
        fundraise = serializer.get_fundraise(self.doc)
        
        self.assertIsNone(fundraise)

    def test_get_grant_returns_none_when_no_grant(self):
        serializer = UnifiedDocumentForListSerializer(self.doc)
        grant = serializer.get_grant(self.doc)
        
        self.assertIsNone(grant)

    def test_get_documents_handles_paper_type(self):
        serializer = UnifiedDocumentForListSerializer(self.doc)
        documents = serializer.get_documents(self.doc)
        
        self.assertIsNotNone(documents)

    def test_get_title_handles_paper(self):
        serializer = UnifiedDocumentForListSerializer(self.doc)
        title = serializer.get_title(self.doc)
        
        self.assertIsNotNone(title)

    def test_get_slug_handles_paper(self):
        serializer = UnifiedDocumentForListSerializer(self.doc)
        slug = serializer.get_slug(self.doc)
        
        self.assertIsNotNone(slug)


class OverviewResponseSerializerTests(TestCase):
    def test_overview_response_serializer(self):
        response_data = {
            "lists": [
                {
                    "id": 1,
                    "name": "Test List",
                    "is_public": False,
                    "created_by": 123,
                    "items": [
                        {"id": 1, "unified_document_id": 10},
                        {"id": 2, "unified_document_id": 11},
                    ],
                }
            ]
        }
        serializer = OverviewResponseSerializer(response_data)
        data = serializer.data
        
        self.assertIn("lists", data)
        self.assertEqual(len(data["lists"]), 1)
        list_data = data["lists"][0]
        self.assertEqual(list_data["id"], 1)
        self.assertEqual(list_data["name"], "Test List")
        self.assertEqual(list_data["is_public"], False)
        self.assertEqual(len(list_data["items"]), 2)
        self.assertEqual(list_data["items"][0]["id"], 1)
        self.assertEqual(list_data["items"][0]["unified_document_id"], 10)


class SimpleUserForListSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")

    def test_author_profile_returns_none_when_user_has_no_author_profile(self):
        if hasattr(self.user, "author_profile") and self.user.author_profile:
            self.user.author_profile.delete()
        serializer = SimpleUserForListSerializer(self.user)
        author_profile = serializer.get_author_profile(self.user)
        self.assertIsNone(author_profile)


class UnifiedDocumentForListSerializerAdditionalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=DISCUSSION)
        self.post = ResearchhubPost.objects.create(
            title="Test Discussion",
            created_by=self.user,
            unified_document=self.unified_doc,
            document_type=DISCUSSION,
        )

    def test_documents_returns_data_for_discussion_type(self):
        serializer = UnifiedDocumentForListSerializer(self.unified_doc)
        documents = serializer.get_documents(self.unified_doc)
        self.assertIsNotNone(documents)

    def test_documents_returns_none_for_unknown_document_type(self):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="UNKNOWN")
        serializer = UnifiedDocumentForListSerializer(unified_doc)
        documents = serializer.get_documents(unified_doc)
        self.assertIsNone(documents)

    def test_reviews_returns_details_when_reviews_exist(self):
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.post.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
        )
        Review.objects.create(
            created_by=self.user,
            score=4.5,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            unified_document=self.unified_doc,
        )
        serializer = UnifiedDocumentForListSerializer(self.unified_doc)
        reviews = serializer.get_reviews(self.unified_doc)
        self.assertIsInstance(reviews, dict)
        self.assertIn("avg", reviews)
        self.assertIn("count", reviews)

    def test_fundraise_returns_none_when_fundraise_serialization_fails(self):
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            goal_amount=100,
            goal_currency="USD",
        )
        serializer = UnifiedDocumentForListSerializer(self.unified_doc)
        fundraise_data = serializer.get_fundraise(self.unified_doc)
        self.assertIsNotNone(fundraise_data)

    def test_grant_returns_none_when_grant_serialization_fails(self):
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            amount=50000,
            currency="USD",
            organization="Test Organization",
        )
        serializer = UnifiedDocumentForListSerializer(self.unified_doc)
        grant_data = serializer.get_grant(self.unified_doc)
        self.assertIsNotNone(grant_data)

    def test_title_returns_post_title_for_discussion_type(self):
        serializer = UnifiedDocumentForListSerializer(self.unified_doc)
        title = serializer.get_title(self.unified_doc)
        self.assertEqual(title, "Test Discussion")

    def test_slug_returns_post_slug_for_discussion_type(self):
        serializer = UnifiedDocumentForListSerializer(self.unified_doc)
        slug = serializer.get_slug(self.unified_doc)
        self.assertIsNotNone(slug)


class UserListOverviewSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)

    def test_lists_returns_empty_list_when_queryset_is_none(self):
        serializer = UserListOverviewSerializer(queryset=None)
        lists = serializer.get_lists(None)
        self.assertEqual(lists, [])

    def test_lists_uses_fallback_path_when_items_are_not_prefetched(self):
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc, created_by=self.user)
        list_obj_not_prefetched = List.objects.get(id=self.list_obj.id)
        serializer = UserListOverviewSerializer(queryset=[list_obj_not_prefetched])
        lists = serializer.get_lists(None)
        self.assertEqual(len(lists), 1)
        self.assertEqual(len(lists[0]["items"]), 1)


