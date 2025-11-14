from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Prefetch, Q
from django.test import TestCase
from django.utils import timezone

from feed.models import FeedEntry
from paper.models import Paper
from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.user_model import User
from user_lists.models import List, ListItem
from user_lists.serializers import ListItemReadSerializer, ListSerializer, OverviewSerializer


class ListSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser")
        self.list = List.objects.create(name="My List", created_by=self.user)

    def test_items_count_excludes_removed_items(self):
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item1 = ListItem.objects.create(parent_list=self.list, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=self.list, unified_document=doc2, created_by=self.user)
        item1.delete()
        
        list_with_count = List.objects.annotate(
            items_count=Count("items", filter=Q(items__is_removed=False))
        ).get(id=self.list.id)
        serializer = ListSerializer(list_with_count)
        
        self.assertEqual(serializer.data["items_count"], 1)

    def test_uses_annotated_count_when_available(self):
        list_with_count = List.objects.annotate(
            items_count=Count("items", filter=Q(items__is_removed=False))
        ).get(id=self.list.id)
        
        serializer = ListSerializer(list_with_count)
        
        self.assertEqual(serializer.data["items_count"], 0)


class ListItemReadSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser")
        self.list = List.objects.create(name="My List", created_by=self.user)
        self.context = {
            'content_type_cache': {
                Paper: ContentType.objects.get_for_model(Paper),
                ResearchhubPost: ContentType.objects.get_for_model(ResearchhubPost),
            }
        }

    def test_serializes_paper_with_feed_entry(self):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        Paper.objects.create(title="Test Paper", uploaded_by=self.user, unified_document=unified_doc)
        item = ListItem.objects.create(parent_list=self.list, unified_document=unified_doc, created_by=self.user)
        
        item = ListItem.objects.select_related("unified_document", "unified_document__paper").prefetch_related("unified_document__posts").get(pk=item.pk)
        serializer = ListItemReadSerializer(item, context=self.context)
        
        self.assertIsNotNone(serializer.data["unified_document"])
        self.assertEqual(serializer.data["unified_document"]["content_type"], "PAPER")

    def test_returns_none_when_no_content(self):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item = ListItem.objects.create(parent_list=self.list, unified_document=unified_doc, created_by=self.user)
        
        serializer = ListItemReadSerializer(item, context=self.context)
        
        self.assertIsNone(serializer.data["unified_document"])

    def test_uses_cached_feed_entries(self):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        paper = Paper.objects.create(title="Test Paper", uploaded_by=self.user, unified_document=unified_doc)
        content_type = ContentType.objects.get_for_model(paper)
        feed_entry = FeedEntry.objects.create(
            content_type=content_type,
            object_id=paper.id,
            user=self.user,
            unified_document=unified_doc,
            action_date=timezone.now()
        )
        item = ListItem.objects.create(parent_list=self.list, unified_document=unified_doc, created_by=self.user)
        
        item = ListItem.objects.prefetch_related(
            Prefetch("unified_document__feed_entries", queryset=FeedEntry.objects.all(), to_attr="cached_feed_entries")
        ).get(pk=item.pk)
        serializer = ListItemReadSerializer(item, context=self.context)
        
        self.assertEqual(serializer.data["unified_document"]["id"], feed_entry.id)

    def test_creates_feed_entry_when_cache_empty(self):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        Paper.objects.create(title="Test Paper", uploaded_by=self.user, unified_document=unified_doc)
        item = ListItem.objects.create(parent_list=self.list, unified_document=unified_doc, created_by=self.user)
        
        item = (
            ListItem.objects
            .select_related("unified_document", "unified_document__paper")
            .prefetch_related(
                Prefetch("unified_document__feed_entries", queryset=FeedEntry.objects.all(), to_attr="cached_feed_entries"),
                "unified_document__posts"
            )
            .get(pk=item.pk)
        )
        serializer = ListItemReadSerializer(item, context=self.context)
        
        self.assertIsNotNone(serializer.data["unified_document"])
        self.assertEqual(serializer.data["unified_document"]["content_type"], "PAPER")


class OverviewSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser")
        self.list = List.objects.create(name="My List", created_by=self.user)

    def test_includes_active_items_only(self):
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item1 = ListItem.objects.create(parent_list=self.list, unified_document=doc1, created_by=self.user)
        item2 = ListItem.objects.create(parent_list=self.list, unified_document=doc2, created_by=self.user)
        item2.delete()
        
        lists = List.objects.filter(id=self.list.id).prefetch_related(
            Prefetch("items", queryset=ListItem.objects.filter(is_removed=False), to_attr="overview_items")
        )
        serializer = OverviewSerializer(lists, many=True, context={"items_limit": 20})
        
        self.assertEqual(len(serializer.data[0]["items"]), 1)
        self.assertEqual(serializer.data[0]["items"][0]["id"], item1.id)
