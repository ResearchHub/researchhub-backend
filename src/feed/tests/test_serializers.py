from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from feed.serializers import (
    BountySerializer,
    CommentSerializer,
    ContentObjectSerializer,
    FeedEntrySerializer,
    PaperSerializer,
    PostSerializer,
)
from hub.models import Hub
from hub.serializers import SimpleHubSerializer
from hub.tests.helpers import create_hub
from paper.models import Paper
from paper.tests.helpers import create_paper
from reputation.related_models.bounty import Bounty
from reputation.related_models.escrow import Escrow
from researchhub_comment.constants import rh_comment_thread_types
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
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

    def test_serializes_paper_with_journal_without_image(self):
        # Create a new journal hub without an image
        journal_without_image = create_hub(
            "Journal No Image", namespace=Hub.Namespace.JOURNAL
        )

        # Create a new paper associated with this journal
        paper = create_paper(
            uploaded_by=self.user,
            title="Test Paper No Journal Image",
        )
        paper.hubs.add(journal_without_image)
        paper.save()

        serializer = PaperSerializer(paper)
        data = serializer.data

        # Verify the journal data is serialized correctly
        self.assertIn("journal", data)
        self.assertEqual(data["journal"]["name"], journal_without_image.name)
        self.assertEqual(data["journal"]["image"], None)


class PostSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("post_creator")
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.DISCUSSION,
        )

        self.post = ResearchhubPost.objects.create(
            title="title1",
            created_by=self.user,
            document_type=document_type.DISCUSSION,
            renderable_text="renderableText1",
            unified_document=self.unified_document,
        )
        self.post.save()

    def test_serializes_post(self):
        serializer = PostSerializer(self.post)
        data = serializer.data

        self.assertEqual(data["id"], self.post.id)
        self.assertEqual(data["hub"], None)
        self.assertEqual(data["renderable_text"], self.post.renderable_text)
        self.assertEqual(data["slug"], self.post.slug)
        self.assertEqual(data["title"], self.post.title)
        self.assertEqual(data["type"], self.post.document_type)


class CommentSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("user1")
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.DISCUSSION,
        )
        self.paper = Paper.objects.create(
            title="paper1", unified_document=self.unified_document
        )
        self.hub = create_hub("Test Hub")
        self.unified_document.hubs.add(self.hub)

        self.thread = RhCommentThreadModel.objects.create(
            thread_type=rh_comment_thread_types.GENERIC_COMMENT,
            object_id=self.paper.id,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
        )

        self.comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_content_type=QUILL_EDITOR,
        )

    def test_serializes_comment(self):
        serializer = CommentSerializer(self.comment)
        data = serializer.data

        self.assertEqual(data["id"], self.comment.id)
        self.assertEqual(data["thread_id"], self.thread.id)
        self.assertEqual(data["parent_id"], None)
        self.assertEqual(
            data["comment_content_type"], self.comment.comment_content_type
        )
        self.assertEqual(
            data["comment_content_json"], self.comment.comment_content_json
        )


class BountySerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("bountyCreator1")
        self.paper = Paper.objects.create(title="testPaper1")
        content_type = ContentType.objects.get_for_model(self.paper)

        self.review_thread = RhCommentThreadModel.objects.create(
            thread_type=rh_comment_thread_types.PEER_REVIEW,
            content_type=content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )

        self.comment = RhCommentModel.objects.create(
            thread=self.review_thread,
            created_by=self.user,
        )

        self.researchhub_document = ResearchhubUnifiedDocument.objects.create()
        self.researchhub_document.paper = self.paper
        self.hub1 = Hub.objects.create(name="testHub1")
        self.hub2 = Hub.objects.create(name="testHub2")
        self.researchhub_document.hubs.add(self.hub1)
        self.researchhub_document.hubs.add(self.hub2)

        self.escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            item=self.researchhub_document,
        )

        self.bounty = Bounty.objects.create(
            amount=300,
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=self.researchhub_document,
            item=self.comment,
            escrow=self.escrow,
            created_by=self.user,
        )

    def test_serializes_bounty(self):
        # Act
        serializer = BountySerializer(self.bounty)
        data = serializer.data

        # Assert
        self.assertEqual(data["id"], self.bounty.id)
        self.assertEqual(data["amount"], self.bounty.amount)
        self.assertEqual(data["bounty_type"], self.bounty.bounty_type)
        self.assertEqual(data["status"], self.bounty.status)

        self.assertIn("hub", data)
        self.assertEqual(data["hub"]["name"], self.hub1.name)

        self.assertIn("paper", data)
        self.assertEqual(data["paper"]["title"], self.paper.title)


class SimpleHubSerializerTests(TestCase):
    def setUp(self):
        self.hub = create_hub("Test Hub")

    def test_serializes_hub(self):
        serializer = SimpleHubSerializer(self.hub)
        data = serializer.data

        self.assertEqual(data["name"], self.hub.name)
        self.assertEqual(data["slug"], self.hub.slug)


class FeedEntrySerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("feed_creator")

        return None

    def test_serializes_paper_feed_entry(self):
        paper = create_paper(uploaded_by=self.user)
        paper.save()

        feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            item=paper,
            created_date=paper.created_date,
            action="PUBLISH",
            action_date=paper.paper_publish_date,
            user=self.user,
            unified_document=paper.unified_document,
        )

        serializer = FeedEntrySerializer(feed_entry)
        data = serializer.data

        self.assertIn("id", data)
        self.assertIn("content_type", data)
        self.assertEqual(data["content_type"], "PAPER")
        self.assertIn("content_object", data)
        self.assertIn("created_date", data)

        # Verify paper data is properly nested
        paper_data = data["content_object"]
        self.assertEqual(paper_data["title"], paper.title)
