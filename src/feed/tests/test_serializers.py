from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from feed.serializers import (
    ContentObjectSerializer,
    FeedEntrySerializer,
    PaperSerializer,
)
from hub.models import Hub
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from topic.models import Topic, UnifiedDocumentTopics
from user.tests.helpers import create_random_default_user


class ContentObjectSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("content_creator")
        self.author = self.user.author_profile
        self.author.profile_image = "https://example.com/profile.jpg"
        self.author.save()
        self.user.refresh_from_db()
        self.hub = create_hub("Test Hub")

    def test_serializes_basic_content_fields(self):
        paper = create_paper(uploaded_by=self.user)
        paper.hubs.add(self.hub)
        paper.save()

        serializer = ContentObjectSerializer(paper)
        data = serializer.data

        self.assertIn("id", data)
        self.assertIn("created_date", data)
        self.assertIn("hub", data)
        self.assertIn("slug", data)
        self.assertEqual(data["hub"]["name"], self.hub.name)


class PaperSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("paper_creator")
        self.author = self.user.author_profile
        self.author.profile_image = "https://example.com/profile.jpg"
        self.author.save()
        self.journal = create_hub("Test Journal", namespace=Hub.Namespace.JOURNAL)

        self.paper = create_paper(
            uploaded_by=self.user,
            title="Test Paper",
        )
        self.paper.abstract = "Test Abstract"
        self.paper.doi = "10.1234/test"
        self.paper.hubs.add(self.journal)
        self.paper.authors.add(self.user.author_profile)
        self.paper.save()

        topic = Topic.objects.create(
            display_name="Test Topic",
        )

        primary_topic = UnifiedDocumentTopics.objects.create(
            topic=topic, unified_document=self.paper.unified_document, is_primary=True
        )

        self.hub = create_hub("Test Hub")
        self.hub.subfield_id = primary_topic.topic.subfield_id
        self.hub.save()
        self.paper.hubs.add(self.hub)

    def test_serializes_paper_specific_fields(self):
        serializer = PaperSerializer(self.paper)
        data = serializer.data

        # Test base fields from ContentObjectSerializer
        self.assertIn("id", data)
        self.assertIn("created_date", data)
        self.assertIn("hub", data)
        self.assertIn("slug", data)

        # Test PaperSerializer specific fields
        self.assertEqual(data["title"], "Test Paper")
        self.assertEqual(data["abstract"], "Test Abstract")
        self.assertEqual(data["doi"], "10.1234/test")
        self.assertIn("journal", data)
        self.assertEqual(data["journal"]["name"], self.journal.name)
        self.assertIn("authors", data)
        self.assertEqual(len(data["authors"]), 1)
        self.assertEqual(data["authors"][0]["first_name"], self.user.first_name)
        self.assertEqual(data["authors"][0]["last_name"], self.user.last_name)
        self.assertEqual(
            data["authors"][0]["profile_image"], "https://example.com/profile.jpg"
        )


class FeedEntrySerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("feed_creator")

        return None

    def test_serializes_paper_feed_entry(self):
        paper = create_paper(uploaded_by=self.user)
        paper.save()

        feed_entry = type(
            "FeedEntry",
            (),
            {
                "id": 1,
                "content_type": "paper",
                "content_object": paper,
                "created_date": paper.created_date,
            },
        )()

        serializer = FeedEntrySerializer(feed_entry)
        data = serializer.data

        self.assertIn("id", data)
        self.assertIn("content_type", data)
        self.assertEqual(data["content_type"], "paper")
        self.assertIn("content_object", data)
        self.assertIn("created_date", data)

        # Verify paper data is properly nested
        paper_data = data["content_object"]
        self.assertEqual(paper_data["title"], paper.title)

    def test_returns_none_for_unknown_content_type(self):
        unknown_obj = type(
            "UnknownType",
            (),
            {
                "id": 1,
                "content_type": "unknown",
                "content_object": None,
                "created_date": "2024-01-01",
            },
        )()

        serializer = FeedEntrySerializer(unknown_obj)
        data = serializer.data

        self.assertIn("content_object", data)
        self.assertIsNone(data["content_object"])
