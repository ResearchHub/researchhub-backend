from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from feed.models import FeedEntry
from feed.serializers import (
    CommentSerializer,
    ContentObjectSerializer,
    FeedEntrySerializer,
    PaperSerializer,
    PostSerializer,
)
from feed.views.common import get_common_serializer_context
from hub.models import Hub
from hub.serializers import SimpleHubSerializer
from hub.tests.helpers import create_hub
from paper.models import Paper
from paper.tests.helpers import create_paper
from purchase.related_models.constants.currency import USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Bounty, Escrow
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
from review.models import Review
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

    @patch(
        "researchhub_document.related_models.researchhub_unified_document_model"
        ".ResearchhubUnifiedDocument.get_primary_hub"
    )
    def test_serializes_basic_content_fields(self, mock_get_primary_hub):
        paper = create_paper(uploaded_by=self.user)
        paper.hubs.add(self.hub)
        paper.save()

        mock_get_primary_hub.return_value = self.hub

        serializer = ContentObjectSerializer(paper)
        data = serializer.data

        self.assertIn("id", data)
        self.assertIn("created_date", data)
        self.assertIn("hub", data)
        self.assertIn("slug", data)
        self.assertEqual(data["hub"]["name"], self.hub.name)

        mock_get_primary_hub.assert_called()


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
            raw_authors=["Test Author", "Test Author 2"],
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
        self.assertIn("raw_authors", data)
        self.assertEqual(data["raw_authors"], ["Test Author", "Test Author 2"])
        self.assertIn("work_type", data)

    def test_serializes_paper_with_work_type(self):
        # Test various work_type values
        work_types = ["article", "preprint", "review", "editorial"]

        for work_type in work_types:
            # Create a paper with the work type
            paper = create_paper(
                uploaded_by=self.user,
                title=f"Test Paper - {work_type}",
            )
            paper.work_type = work_type
            paper.save()

            # Serialize and check
            serializer = PaperSerializer(paper)
            data = serializer.data

            # Verify the work_type is serialized correctly
            self.assertIn("work_type", data)
            self.assertEqual(data["work_type"], work_type)

    def test_serializes_paper_with_journal_without_image(self):
        # Create a new journal hub without an image
        journal_without_image = create_hub(
            "Journal No Image", namespace=Hub.Namespace.JOURNAL
        )

        paper = create_paper(
            uploaded_by=self.user,
            title="Test Paper No Journal Image",
        )
        paper.hubs.add(journal_without_image)
        paper.save()

        serializer = PaperSerializer(paper)
        data = serializer.data

        self.assertIn("journal", data)
        self.assertEqual(data["journal"]["name"], journal_without_image.name)
        self.assertEqual(data["journal"]["image"], None)

    def test_serializes_paper_with_bounties(self):
        """Test that paper serializes with bounties field when bounties exist"""
        # Create an escrow for the bounty
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=100,
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
        )

        # Create a bounty attached to the paper's unified document
        bounty = Bounty.objects.create(
            amount=100,
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=self.paper.unified_document,
            item_content_type=ContentType.objects.get_for_model(self.paper),
            item_object_id=self.paper.id,
            escrow=escrow,
            created_by=self.user,
        )

        # Serialize the paper
        serializer = PaperSerializer(self.paper)
        data = serializer.data

        # Verify bounties field exists and contains the bounty
        self.assertIn("bounties", data)
        self.assertIsInstance(data["bounties"], list)
        self.assertEqual(len(data["bounties"]), 1)

        # Verify bounty data
        bounty_data = data["bounties"][0]
        self.assertEqual(bounty_data["id"], bounty.id)
        self.assertEqual(bounty_data["status"], bounty.status)
        self.assertEqual(bounty_data["bounty_type"], bounty.bounty_type)


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
        self.assertIsNone(data["fundraise"])

    def test_serializes_preregistration_post_with_fundraise(self):
        from decimal import Decimal

        from purchase.models import Fundraise
        from purchase.services.fundraise_service import FundraiseService

        # Create a preregistration post
        preregistration_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.PREREGISTRATION,
        )

        preregistration_post = ResearchhubPost.objects.create(
            title="Preregistration Title",
            created_by=self.user,
            document_type=document_type.PREREGISTRATION,
            renderable_text="This is a preregistration post with fundraising",
            unified_document=preregistration_doc,
        )

        # Create a fundraise for the preregistration
        fundraise_service = FundraiseService()
        goal_amount = Decimal("100.00")
        fundraise = fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=preregistration_doc,
            goal_amount=goal_amount,
            goal_currency=USD,
            status=Fundraise.OPEN,
        )

        # Get the context with the field specifications
        context = get_common_serializer_context()

        # Mock the RscExchangeRate.usd_to_rsc method to avoid database dependency
        with patch.object(
            RscExchangeRate, "usd_to_rsc", return_value=200.0
        ), patch.object(
            Fundraise,
            "get_amount_raised",
            side_effect=lambda currency: 50.0 if currency == USD else 100.0,
        ):
            # Serialize the post with the context
            serializer = PostSerializer(preregistration_post, context=context)
            data = serializer.data

            # Assert basic post fields
            self.assertEqual(data["id"], preregistration_post.id)
            self.assertEqual(data["title"], preregistration_post.title)
            self.assertEqual(data["type"], preregistration_post.document_type)

            # Assert fundraise data
            self.assertIsNotNone(data["fundraise"])
            self.assertEqual(data["fundraise"]["id"], fundraise.id)
            self.assertEqual(data["fundraise"]["status"], fundraise.status)

            # Check created_by field
            self.assertIn("created_by", data["fundraise"])
            created_by = data["fundraise"]["created_by"]
            self.assertEqual(created_by["id"], self.user.id)
            self.assertIn("first_name", created_by)
            self.assertIn("last_name", created_by)

            # Check author_profile field
            self.assertIn("author_profile", created_by)
            author_profile = created_by["author_profile"]
            expected_profile_fields = [
                "id",
                "first_name",
                "last_name",
                "created_date",
                "updated_date",
                "profile_image",
                "is_verified",
            ]
            for field in expected_profile_fields:
                self.assertIn(field, author_profile)

            # Verify only the expected fields are present in created_by
            expected_user_fields = ["id", "author_profile", "first_name", "last_name"]
            self.assertEqual(set(created_by.keys()), set(expected_user_fields))

            # Verify only the expected fields are present in author_profile
            self.assertEqual(set(author_profile.keys()), set(expected_profile_fields))

            # Check goal_amount which is now a dictionary with usd and rsc values
            self.assertIn("goal_amount", data["fundraise"])
            self.assertIn("usd", data["fundraise"]["goal_amount"])
            self.assertIn("rsc", data["fundraise"]["goal_amount"])
            self.assertEqual(
                data["fundraise"]["goal_amount"]["usd"], float(fundraise.goal_amount)
            )
            # Check that the mocked RSC value is used
            self.assertEqual(data["fundraise"]["goal_amount"]["rsc"], 200.0)

            self.assertEqual(
                data["fundraise"]["goal_currency"], fundraise.goal_currency
            )

            # Check amount_raised which is now a dictionary with usd and rsc values
            self.assertIn("amount_raised", data["fundraise"])
            self.assertIn("usd", data["fundraise"]["amount_raised"])
            self.assertIn("rsc", data["fundraise"]["amount_raised"])
            # Check that the mocked amount_raised values are used
            self.assertEqual(data["fundraise"]["amount_raised"]["usd"], 50.0)
            self.assertEqual(data["fundraise"]["amount_raised"]["rsc"], 100.0)

            # Check contributors which is now a dictionary with total and top values
            self.assertIn("contributors", data["fundraise"])
            self.assertIn("total", data["fundraise"]["contributors"])
            self.assertEqual(data["fundraise"]["contributors"]["total"], 0)
            self.assertIn("top", data["fundraise"]["contributors"])

    def test_serializes_post_image_url(self):
        """Test that image_url is correctly serialized for posts."""
        # Post without image (using self.post from setUp)
        serializer_no_image = PostSerializer(self.post)
        data_no_image = serializer_no_image.data
        self.assertIn("image_url", data_no_image)
        self.assertIsNone(data_no_image["image_url"])

        # Create post WITH image
        unified_doc_with_image = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.DISCUSSION
        )
        dummy_image = SimpleUploadedFile(
            "test_serializer_image.jpg", b"file_content", content_type="image/jpeg"
        )
        post_with_image = ResearchhubPost.objects.create(
            title="Post With Image Serializer Test",
            created_by=self.user,
            document_type=document_type.DISCUSSION,
            unified_document=unified_doc_with_image,
            image=dummy_image,
        )

        serializer_with_image = PostSerializer(post_with_image)
        data_with_image = serializer_with_image.data
        self.assertIn("image_url", data_with_image)
        self.assertIsNotNone(data_with_image["image_url"])
        self.assertEqual(
            data_with_image["image_url"],
            default_storage.url(post_with_image.image.name),
        )

    def test_serializes_post_with_bounties(self):
        """Test that post serializes with bounties field when bounties exist"""
        # Create an escrow for the bounty
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=200,
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
        )

        # Create a bounty attached to the post's unified document
        bounty = Bounty.objects.create(
            amount=200,
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.ANSWER,
            unified_document=self.post.unified_document,
            item_content_type=ContentType.objects.get_for_model(self.post),
            item_object_id=self.post.id,
            escrow=escrow,
            created_by=self.user,
        )

        # Serialize the post
        serializer = PostSerializer(self.post)
        data = serializer.data

        # Verify bounties field exists and contains the bounty
        self.assertIn("bounties", data)
        self.assertIsInstance(data["bounties"], list)
        self.assertEqual(len(data["bounties"]), 1)

        # Verify bounty data
        bounty_data = data["bounties"][0]
        self.assertEqual(bounty_data["id"], bounty.id)
        self.assertEqual(bounty_data["status"], bounty.status)
        self.assertEqual(bounty_data["bounty_type"], bounty.bounty_type)


class CommentSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("user1")
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.PAPER,
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

        # Create a post for testing post serialization
        self.post = ResearchhubPost.objects.create(
            title="Test Post",
            document_type=document_type.DISCUSSION,
            created_by=self.user,
            unified_document=self.unified_document,
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
        self.assertIsNone(data["review"])

        # Test author field
        self.assertIn("author", data)

    def test_serializes_comment_with_review(self):
        review = Review.objects.create(
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.unified_document,
        )

        serializer = CommentSerializer(self.comment)
        data = serializer.data

        self.assertIsNotNone(data["review"])
        self.assertEqual(data["review"]["id"], review.id)
        self.assertEqual(data["review"]["score"], 8.5)
        self.assertEqual(data["review"]["created_by"], self.user.id)
        self.assertEqual(data["review"]["unified_document"], self.unified_document.id)

    def test_serializes_comment_with_paper(self):
        serializer = CommentSerializer(self.comment)
        data = serializer.data

        self.assertIsNotNone(data["paper"])
        self.assertEqual(data["paper"]["title"], self.paper.title)

    def test_serializes_comment_with_parent_comment(self):
        # Create a reply to the existing comment
        child_comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_content_type=QUILL_EDITOR,
            comment_content_json={"ops": [{"insert": "This is a reply comment"}]},
            parent=self.comment,
        )

        child_child_comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_content_type=QUILL_EDITOR,
            comment_content_json={
                "ops": [{"insert": "This is a reply to the reply comment"}]
            },
            parent=child_comment,
        )

        serializer = CommentSerializer(child_child_comment)
        data = serializer.data

        # Validate the parent_id and parent_comment fields
        self.assertIsNotNone(data["parent_comment"])
        self.assertEqual(data["parent_comment"]["id"], child_comment.id)
        self.assertEqual(data["parent_comment"]["thread_id"], self.thread.id)
        self.assertEqual(
            data["parent_comment"]["comment_content_type"],
            child_comment.comment_content_type,
        )

        # Validate the parent of the parent
        self.assertIsNotNone(data["parent_comment"]["parent_comment"])
        self.assertEqual(
            data["parent_comment"]["parent_comment"]["id"], self.comment.id
        )
        self.assertEqual(
            data["parent_comment"]["parent_comment"]["thread_id"], self.thread.id
        )
        self.assertEqual(
            data["parent_comment"]["parent_comment"]["comment_content_type"],
            self.comment.comment_content_type,
        )

    def test_serializes_comment_with_post(self):
        # Create a thread for the existing post
        post_thread = RhCommentThreadModel.objects.create(
            thread_type=rh_comment_thread_types.GENERIC_COMMENT,
            object_id=self.post.id,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
        )

        # Create a comment for the post
        post_comment = RhCommentModel.objects.create(
            thread=post_thread,
            created_by=self.user,
            comment_content_type=QUILL_EDITOR,
        )

        serializer = CommentSerializer(post_comment)
        data = serializer.data

        self.assertIsNotNone(data["post"])
        self.assertEqual(data["post"]["title"], self.post.title)


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

    @patch(
        "researchhub_document.related_models.researchhub_unified_document_model"
        ".ResearchhubUnifiedDocument.get_primary_hub"
    )
    def test_serializes_paper_feed_entry(self, mock_get_primary_hub):
        paper = create_paper(uploaded_by=self.user)
        paper.score = 42
        paper.discussion_count = 15
        paper.save()

        hub = create_hub("Test Hub")
        mock_get_primary_hub.return_value = hub

        # Mock the get_review_details method to return test review metrics
        review_metrics = {"avg": 4.5, "count": 3}
        with patch.object(
            paper.unified_document, "get_review_details", return_value=review_metrics
        ):
            feed_entry = FeedEntry.objects.create(
                content_type=ContentType.objects.get_for_model(Paper),
                object_id=paper.id,
                item=paper,
                created_date=paper.created_date,
                action="PUBLISH",
                action_date=paper.paper_publish_date,
                metrics={"votes": 42, "comments": 15, "review_metrics": review_metrics},
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

            paper_data = data["content_object"]
            self.assertEqual(paper_data["title"], paper.title)

            # Verify metrics field exists and contains expected values
            self.assertIn("metrics", data)
            self.assertIsInstance(data["metrics"], dict)
            self.assertIn("votes", data["metrics"])
            self.assertIn("comments", data["metrics"])
            self.assertEqual(data["metrics"]["votes"], 42)
            self.assertEqual(data["metrics"]["comments"], 15)

            # Verify review_metrics are included
            self.assertIn("review_metrics", data["metrics"])
            self.assertEqual(data["metrics"]["review_metrics"]["avg"], 4.5)
            self.assertEqual(data["metrics"]["review_metrics"]["count"], 3)

            mock_get_primary_hub.assert_called()

    @patch(
        "researchhub_document.related_models.researchhub_unified_document_model."
        "ResearchhubUnifiedDocument.get_primary_hub"
    )
    def test_serializes_post_feed_entry(self, mock_get_primary_hub):
        """Test serialization of post feed entries with metrics"""
        # Create a hub
        hub = create_hub("Test Hub")
        mock_get_primary_hub.return_value = hub

        # Create a post with metrics
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.POSTS,
        )

        post = ResearchhubPost.objects.create(
            title="Test Post",
            created_by=self.user,
            document_type=document_type.POSTS,
            renderable_text="This is a test post",
            unified_document=unified_document,
            score=25,
            discussion_count=8,
        )

        # Create a feed entry for the post
        post_feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            item=post,
            created_date=post.created_date,
            action="PUBLISH",
            action_date=post.created_date,
            metrics={"votes": 25, "comments": 8},
            user=self.user,
            unified_document=post.unified_document,
        )

        # Serialize the feed entry
        serializer = FeedEntrySerializer(post_feed_entry)
        data = serializer.data

        # Verify basic feed entry fields
        self.assertIn("id", data)
        self.assertIn("content_type", data)
        self.assertEqual(data["content_type"], "RESEARCHHUBPOST")
        self.assertIn("content_object", data)
        self.assertIn("created_date", data)

        # Verify post data
        post_data = data["content_object"]
        self.assertEqual(post_data["title"], post.title)

        # Verify metrics field exists and contains expected values
        self.assertIn("metrics", data)
        self.assertIsInstance(data["metrics"], dict)
        self.assertIn("votes", data["metrics"])
        self.assertIn("comments", data["metrics"])
        self.assertEqual(data["metrics"]["votes"], 25)
        self.assertEqual(data["metrics"]["comments"], 8)

        mock_get_primary_hub.assert_called()

    @patch(
        "researchhub_document.related_models.researchhub_unified_document_model."
        "ResearchhubUnifiedDocument.get_primary_hub"
    )
    def test_serializes_comment_feed_entry(self, mock_get_primary_hub):
        """Test serialization of comment feed entries with metrics"""
        # Create a hub
        hub = create_hub("Test Hub")
        mock_get_primary_hub.return_value = hub

        # Create a paper for the comment
        paper = create_paper(uploaded_by=self.user)

        # Create a comment thread and comment with metrics
        thread = RhCommentThreadModel.objects.create(
            thread_type=rh_comment_thread_types.GENERIC_COMMENT,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=self.user,
        )

        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
            score=15,
        )

        # Create actual child comments instead of mocking children_count
        for i in range(3):
            RhCommentModel.objects.create(
                thread=thread,
                created_by=self.user,
                comment_content_json={"ops": [{"insert": f"Reply {i+1}"}]},
                parent=comment,
            )

        # Create a feed entry for the comment
        comment_feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            item=comment,
            created_date=comment.created_date,
            action="PUBLISH",
            action_date=comment.created_date,
            metrics={"votes": 15},
            user=self.user,
            unified_document=paper.unified_document,
        )

        # Serialize the feed entry
        serializer = FeedEntrySerializer(comment_feed_entry)
        data = serializer.data

        # Verify basic feed entry fields
        self.assertIn("id", data)
        self.assertIn("content_type", data)
        self.assertEqual(data["content_type"], "RHCOMMENTMODEL")
        self.assertIn("content_object", data)
        self.assertIn("created_date", data)

        # Verify metrics field exists and contains expected values
        self.assertIn("metrics", data)
        self.assertIsInstance(data["metrics"], dict)
        self.assertIn("votes", data["metrics"])
        self.assertEqual(data["metrics"]["votes"], 15)

        mock_get_primary_hub.assert_called()
