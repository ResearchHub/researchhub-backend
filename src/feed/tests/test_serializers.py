from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import PropertyMock, patch

import pytz
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

from feed.models import FeedEntry
from feed.serializers import (
    ContentObjectSerializer,
    FeedEntrySerializer,
    FundingFeedEntrySerializer,
    PaperSerializer,
    PostSerializer,
    SimpleReviewSerializer,
    SimpleUserSerializer,
)
from feed.views.feed_view_mixin import FeedViewMixin
from hub.models import Hub
from hub.serializers import SimpleHubSerializer
from hub.tests.helpers import create_hub
from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from paper.models import Figure, Paper
from paper.tests.helpers import create_paper
from purchase.models import Fundraise, Grant, GrantApplication, Purchase
from purchase.related_models.constants.currency import USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Bounty, Escrow
from researchhub_access_group.models import Permission
from researchhub_comment.constants import rh_comment_thread_types
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from review.models import Review
from topic.models import Topic, UnifiedDocumentTopics
from user.related_models.user_verification_model import UserVerification
from user.tests.helpers import create_random_default_user
from utils.test_helpers import AWSMockTestCase


class SimpleUserSerializerTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("test_user_serializer")
        # Create a verification record with non-APPROVED status
        UserVerification.objects.create(
            user=self.user,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            status=UserVerification.Status.APPROVED,
            verified_by=UserVerification.Type.MANUAL,
            external_id="test-id",
        )

    def test_serializes_basic_user_fields(self):
        # Test that other basic fields are included
        serializer = SimpleUserSerializer(self.user)
        data = serializer.data

        self.assertEqual(data["id"], self.user.id)
        self.assertEqual(data["first_name"], self.user.first_name)
        self.assertEqual(data["last_name"], self.user.last_name)
        self.assertIn("is_verified", data)
        self.assertTrue(data["is_verified"])


class ContentObjectSerializerTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("content_creator")
        self.author = self.user.author_profile
        self.author.profile_image = "https://example.com/profile.jpg"
        self.author.save()
        self.user.refresh_from_db()
        self.hub = create_hub("Test Hub")
        self.category = create_hub("Chemistry", namespace=Hub.Namespace.CATEGORY)
        self.subcategory = create_hub(
            "Organic Chemistry", namespace=Hub.Namespace.SUBCATEGORY
        )

    @patch(
        "researchhub_document.related_models.researchhub_unified_document_model"
        ".ResearchhubUnifiedDocument.get_primary_hub"
    )
    def test_serializes_basic_content_fields(self, mock_get_primary_hub):
        paper = create_paper(uploaded_by=self.user)
        paper.hubs.add(self.hub)
        paper.unified_document.hubs.add(self.category)
        paper.unified_document.hubs.add(self.subcategory)
        paper.save()

        mock_get_primary_hub.return_value = self.hub

        serializer = ContentObjectSerializer(paper)
        data = serializer.data

        self.assertIn("id", data)
        self.assertIn("created_date", data)
        self.assertIn("hub", data)
        self.assertIn("category", data)
        self.assertIn("subcategory", data)
        self.assertIn("slug", data)
        self.assertEqual(data["hub"]["name"], self.hub.name)
        # Verify category and subcategory are properly serialized
        self.assertIsNotNone(data["category"])
        self.assertEqual(data["category"]["id"], self.category.id)
        self.assertIsNotNone(data["subcategory"])
        self.assertEqual(data["subcategory"]["id"], self.subcategory.id)

        mock_get_primary_hub.assert_called()


test_storage = FileSystemStorage()


@patch.object(Figure._meta.get_field("file"), "storage", test_storage)
@patch.object(Figure._meta.get_field("thumbnail"), "storage", test_storage)
class PaperSerializerTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("paper_creator")
        self.author = self.user.author_profile
        self.author.profile_image = "https://example.com/profile.jpg"
        self.author.save()
        self.journal = create_hub("Test Journal", namespace=Hub.Namespace.JOURNAL)
        self.category = create_hub("Biology", namespace=Hub.Namespace.CATEGORY)
        self.subcategory = create_hub(
            "Molecular Biology", namespace=Hub.Namespace.SUBCATEGORY
        )

        self.paper = create_paper(
            uploaded_by=self.user,
            title="Test Paper",
            raw_authors=["Test Author", "Test Author 2"],
        )
        self.paper.abstract = "Test Abstract"
        self.paper.doi = "10.1234/test"
        self.paper.hubs.add(self.journal)
        self.paper.unified_document.hubs.add(self.category)
        self.paper.unified_document.hubs.add(self.subcategory)
        self.paper.authors.add(self.user.author_profile)
        self.paper.save()

        topic = Topic.objects.create(
            display_name="Test Topic",
        )

        primary_topic = UnifiedDocumentTopics.objects.create(
            topic=topic, unified_document=self.paper.unified_document, is_primary=True
        )

        self.thread = RhCommentThreadModel.objects.create(
            thread_type=rh_comment_thread_types.PEER_REVIEW,
            object_id=self.paper.id,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
        )

        self.comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_content_type=QUILL_EDITOR,
        )

        Review.objects.create(
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.paper.unified_document,
        )

        self.hub = create_hub("Test Hub")
        self.hub.subfield_id = primary_topic.topic.subfield_id
        self.hub.save()
        self.paper.hubs.add(self.hub)

    def test_serializes_paper_specific_fields(self):
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", str(self.journal.id)):
            serializer = PaperSerializer(self.paper)
            data = serializer.data

            # Test base fields from ContentObjectSerializer
            self.assertIn("id", data)
            self.assertIn("created_date", data)
            self.assertIn("hub", data)
            self.assertIn("category", data)
            self.assertIn("subcategory", data)
            self.assertIn("slug", data)
            self.assertIn("reviews", data)

            # Verify category and subcategory are properly serialized
            self.assertIsNotNone(data["category"])
            self.assertEqual(data["category"]["id"], self.category.id)
            self.assertIsNotNone(data["subcategory"])
            self.assertEqual(data["subcategory"]["id"], self.subcategory.id)

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

        with patch.object(
            settings, "RESEARCHHUB_JOURNAL_ID", str(journal_without_image.id)
        ):
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
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", str(self.journal.id)):
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

    def test_serializes_paper_with_purchases(self):
        # Create a purchase for the unified document
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="10.0",
            paid_status=Purchase.PAID,
        )

        # Serialize and check
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", str(self.journal.id)):
            serializer = PaperSerializer(self.paper)
            data = serializer.data

            # Verify purchases are included
            self.assertIn("purchases", data)
            self.assertIsInstance(data["purchases"], list)
            self.assertEqual(len(data["purchases"]), 1)

            # Verify purchase data is correct
            purchase_data = data["purchases"][0]
            self.assertEqual(purchase_data["id"], purchase.id)
            self.assertEqual(purchase_data["amount"], purchase.amount)
            self.assertIn("user", purchase_data)

    def test_prioritizes_researchhub_journal(self):
        """
        Test that the ResearchHub Journal is prioritized when multiple journals exist.
        """
        # Create regular journal
        regular_journal = create_hub("Regular Journal", namespace=Hub.Namespace.JOURNAL)

        # Create ResearchHub journal
        researchhub_journal = create_hub(
            "ResearchHub Journal", namespace=Hub.Namespace.JOURNAL
        )

        # Create a paper with both journals
        paper = create_paper(
            uploaded_by=self.user,
            title="Multi-Journal Paper",
        )
        paper.hubs.add(regular_journal)
        paper.hubs.add(researchhub_journal)
        paper.save()

        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", researchhub_journal.id):
            serializer = PaperSerializer(paper)
            data = serializer.data

            self.assertIn("journal", data)
            self.assertEqual(data["journal"]["name"], "ResearchHub Journal")
            self.assertEqual(data["journal"]["id"], researchhub_journal.id)

    @patch.object(settings, "RESEARCHHUB_JOURNAL_ID", 999999)
    @patch.object(ResearchhubUnifiedDocument, "get_journal")
    def test_get_journal(self, mock_get_journal):
        """
        Test that the first journal is used when no prioritized journal exists.
        """
        # Create two regular journals
        journal1 = create_hub("Journal One", namespace=Hub.Namespace.JOURNAL)
        journal2 = create_hub("Journal Two", namespace=Hub.Namespace.JOURNAL)
        mock_get_journal.return_value = journal1

        # Create a paper with both journals
        paper = create_paper(
            uploaded_by=self.user,
            title="Paper without priority journals",
        )
        paper.hubs.add(journal1)
        paper.hubs.add(journal2)
        paper.save()

        serializer = PaperSerializer(paper)
        data = serializer.data

        self.assertIn("journal", data)
        # Should return one of the journals (first one found)
        self.assertEqual(data["journal"]["id"], journal1.id)

    def test_serializes_paper_primary_image(self):
        """Test that primary_image is correctly serialized for papers."""
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", str(self.journal.id)):
            # Paper without primary image
            serializer_no_image = PaperSerializer(self.paper)
            data_no_image = serializer_no_image.data
            self.assertIn("primary_image", data_no_image)
            self.assertIsNone(data_no_image["primary_image"])

            # Create a primary figure
            dummy_image = SimpleUploadedFile(
                "test_figure.jpg", b"file_content", content_type="image/jpeg"
            )
            primary_figure = Figure.objects.create(
                paper=self.paper,
                file=dummy_image,
                figure_type=Figure.FIGURE,
                is_primary=True,
            )

            serializer_with_image = PaperSerializer(self.paper)
            data_with_image = serializer_with_image.data
            self.assertIn("primary_image", data_with_image)
            self.assertIsNotNone(data_with_image["primary_image"])
            self.assertEqual(
                data_with_image["primary_image"],
                default_storage.url(primary_figure.file.name),
            )

    def test_serializes_paper_primary_image_without_file(self):
        """Test that primary_image returns None when figure has no file."""
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", str(self.journal.id)):
            # Create a primary figure without a file
            Figure.objects.create(
                paper=self.paper,
                file=None,
                figure_type=Figure.FIGURE,
                is_primary=True,
            )

            serializer = PaperSerializer(self.paper)
            data = serializer.data
            self.assertIn("primary_image", data)
            self.assertIsNone(data["primary_image"])

    def test_serializes_paper_primary_image_handles_exception(self):
        """Test that primary_image returns None when file.url raises exception."""
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", str(self.journal.id)):
            # Create a primary figure with a file
            dummy_image = SimpleUploadedFile(
                "test_figure.jpg", b"file_content", content_type="image/jpeg"
            )
            primary_figure = Figure.objects.create(
                paper=self.paper,
                file=dummy_image,
                figure_type=Figure.FIGURE,
                is_primary=True,
            )

            # Refresh from DB to get the actual file object
            primary_figure.refresh_from_db()

            # Patch the file.url property to raise an exception
            # This simulates scenarios like storage errors, file corruption, etc.
            # We need to patch it as a property since url is a property on
            # Django file fields
            original_file = primary_figure.file
            mock_url_property = PropertyMock(side_effect=Exception("Storage error"))
            with patch.object(type(original_file), "url", mock_url_property):
                serializer = PaperSerializer(self.paper)
                data = serializer.data
                self.assertIn("primary_image", data)
                # Should return None when exception occurs
                self.assertIsNone(data["primary_image"])

    def test_serializes_paper_primary_image_thumbnail_handles_exception(self):
        """Test that primary_image_thumbnail returns None when thumbnail.url
        raises exception."""
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", str(self.journal.id)):
            # Create a primary figure with a thumbnail
            dummy_image = SimpleUploadedFile(
                "test_figure.jpg", b"file_content", content_type="image/jpeg"
            )
            dummy_thumbnail = SimpleUploadedFile(
                "test_thumbnail.jpg", b"thumbnail_content", content_type="image/jpeg"
            )
            primary_figure = Figure.objects.create(
                paper=self.paper,
                file=dummy_image,
                thumbnail=dummy_thumbnail,
                figure_type=Figure.FIGURE,
                is_primary=True,
            )

            # Refresh from DB to get the actual thumbnail object
            primary_figure.refresh_from_db()

            # Patch the thumbnail.url property to raise an exception
            # This simulates scenarios like storage errors, file corruption, etc.
            original_thumbnail = primary_figure.thumbnail
            mock_url_property = PropertyMock(side_effect=Exception("Storage error"))
            with patch.object(type(original_thumbnail), "url", mock_url_property):
                serializer = PaperSerializer(self.paper)
                data = serializer.data
                self.assertIn("primary_image_thumbnail", data)
                # Should return None when exception occurs
                self.assertIsNone(data["primary_image_thumbnail"])


class PostSerializerTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("post_creator")
        self.category = create_hub("Science", namespace=Hub.Namespace.CATEGORY)
        self.subcategory = create_hub(
            "Neuroscience", namespace=Hub.Namespace.SUBCATEGORY
        )
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.DISCUSSION,
        )
        self.unified_document.hubs.add(self.category)
        self.unified_document.hubs.add(self.subcategory)

        self.post = ResearchhubPost.objects.create(
            title="title1",
            created_by=self.user,
            document_type=document_type.DISCUSSION,
            renderable_text="renderableText1",
            unified_document=self.unified_document,
        )
        self.post.save()

        self.thread = RhCommentThreadModel.objects.create(
            thread_type=rh_comment_thread_types.PEER_REVIEW,
            object_id=self.post.id,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
        )

        self.comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_content_type=QUILL_EDITOR,
        )

        self.review = Review.objects.create(
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.post.unified_document,
        )

    def test_serializes_post(self):
        serializer = PostSerializer(self.post)
        data = serializer.data

        self.assertEqual(data["id"], self.post.id)
        self.assertIn("hub", data)
        self.assertIn("category", data)
        self.assertIn("subcategory", data)
        # Verify category and subcategory are properly serialized
        self.assertIsNotNone(data["category"])
        self.assertEqual(data["category"]["id"], self.category.id)
        self.assertIsNotNone(data["subcategory"])
        self.assertEqual(data["subcategory"]["id"], self.subcategory.id)
        self.assertEqual(data["renderable_text"], self.post.renderable_text)
        self.assertEqual(data["slug"], self.post.slug)
        self.assertEqual(data["title"], self.post.title)
        self.assertEqual(data["type"], self.post.document_type)
        self.assertIsNone(data["fundraise"])
        self.assertIn("reviews", data)

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
        context = FeedViewMixin().get_common_serializer_context()

        # Mock the RscExchangeRate.usd_to_rsc method to avoid database dependency
        with (
            patch.object(RscExchangeRate, "usd_to_rsc", return_value=200.0),
            patch.object(
                Fundraise,
                "get_amount_raised",
                side_effect=lambda currency: 50.0 if currency == USD else 100.0,
            ),
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

    def test_serializes_post_with_purchases(self):
        # Create a purchase for the unified document
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.post.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="5.0",
            paid_status=Purchase.PAID,
        )

        # Serialize and check
        serializer = PostSerializer(self.post)
        data = serializer.data

        # Verify purchases are included
        self.assertIn("purchases", data)
        self.assertIsInstance(data["purchases"], list)
        self.assertEqual(len(data["purchases"]), 1)

        # Verify purchase data is correct
        purchase_data = data["purchases"][0]
        self.assertEqual(purchase_data["id"], purchase.id)
        self.assertEqual(purchase_data["amount"], purchase.amount)
        self.assertIn("user", purchase_data)

    def test_serializes_grant_post_with_grant(self):
        """Test that grant posts serialize with grant data"""
        from datetime import datetime, timedelta

        import pytz

        # Create a grant post
        grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.GRANT,
        )

        grant_post = ResearchhubPost.objects.create(
            title="Test Grant Post",
            created_by=self.user,
            document_type=document_type.GRANT,
            renderable_text="This is a grant post",
            unified_document=grant_unified_doc,
        )

        # Create a grant for the post
        end_date = datetime.now(pytz.UTC) + timedelta(days=30)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_unified_doc,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="National Science Foundation",
            description="Research grant for innovative AI applications",
            status=Grant.OPEN,
            end_date=end_date,
        )

        # Add some contacts to the grant
        contact_user = create_random_default_user("grant_contact")
        grant.contacts.add(contact_user)

        # Get the context with the field specifications like in the real implementation
        context = FeedViewMixin().get_common_serializer_context()

        # Serialize the grant post
        serializer = PostSerializer(grant_post, context=context)
        data = serializer.data

        # Assert basic post fields
        self.assertEqual(data["id"], grant_post.id)
        self.assertEqual(data["title"], grant_post.title)
        self.assertEqual(data["type"], grant_post.document_type)

        # Assert grant data is present
        self.assertIsNotNone(data["grant"])
        grant_data = data["grant"]

        # Check basic grant fields
        self.assertEqual(grant_data["id"], grant.id)
        self.assertEqual(grant_data["status"], grant.status)
        self.assertEqual(grant_data["currency"], grant.currency)
        self.assertEqual(grant_data["organization"], grant.organization)
        self.assertEqual(grant_data["description"], grant.description)

        # Check amount field (should be a dict with usd and rsc values)
        self.assertIn("amount", grant_data)
        amount_data = grant_data["amount"]
        self.assertIn("usd", amount_data)
        self.assertEqual(amount_data["usd"], float(grant.amount))

        # Check date fields
        self.assertIn("start_date", grant_data)
        self.assertIn("end_date", grant_data)

        # Check status fields
        self.assertIn("is_expired", grant_data)
        self.assertIn("is_active", grant_data)
        self.assertFalse(grant_data["is_expired"])  # Should not be expired
        self.assertTrue(grant_data["is_active"])  # Should be active

        # Check created_by field
        self.assertIn("created_by", grant_data)
        created_by = grant_data["created_by"]
        self.assertEqual(created_by["id"], self.user.id)

        # Check contacts field
        self.assertIn("contacts", grant_data)
        contacts = grant_data["contacts"]
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["id"], contact_user.id)

        # Check applications field (should be empty array initially)
        self.assertIn("applications", grant_data)
        self.assertEqual(grant_data["applications"], [])

    def test_serializes_grant_post_with_applications(self):
        """Test that grant posts serialize with application data when applications
        exist"""
        from datetime import datetime, timedelta

        import pytz

        # Create a grant post
        grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.GRANT,
        )

        grant_post = ResearchhubPost.objects.create(
            title="Grant Post with Applications",
            created_by=self.user,
            document_type=document_type.GRANT,
            renderable_text="This grant has applications",
            unified_document=grant_unified_doc,
        )

        # Create a grant
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_unified_doc,
            amount=Decimal("25000.00"),
            currency="USD",
            organization="Test Foundation",
            description="Grant with applications",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=60),
        )

        # Create applicants and their preregistration posts
        applicant1 = create_random_default_user("applicant1")
        applicant2 = create_random_default_user("applicant2")

        # Create preregistration posts for applications
        prereg_doc1 = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.PREREGISTRATION,
        )
        prereg_post1 = ResearchhubPost.objects.create(
            title="Preregistration 1",
            created_by=applicant1,
            document_type=document_type.PREREGISTRATION,
            unified_document=prereg_doc1,
        )

        prereg_doc2 = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.PREREGISTRATION,
        )
        prereg_post2 = ResearchhubPost.objects.create(
            title="Preregistration 2",
            created_by=applicant2,
            document_type=document_type.PREREGISTRATION,
            unified_document=prereg_doc2,
        )

        # Create grant applications
        application1 = GrantApplication.objects.create(
            grant=grant,
            preregistration_post=prereg_post1,
            applicant=applicant1,
        )

        application2 = GrantApplication.objects.create(
            grant=grant,
            preregistration_post=prereg_post2,
            applicant=applicant2,
        )

        # Get the context
        context = FeedViewMixin().get_common_serializer_context()

        # Serialize the grant post
        serializer = PostSerializer(grant_post, context=context)
        data = serializer.data

        # Assert grant data includes applications
        self.assertIsNotNone(data["grant"])
        grant_data = data["grant"]

        # Check applications field
        self.assertIn("applications", grant_data)
        applications = grant_data["applications"]
        self.assertEqual(len(applications), 2)

        # Check first application structure
        app1_data = applications[0]
        self.assertIn("id", app1_data)
        self.assertIn("created_date", app1_data)
        self.assertIn("applicant", app1_data)
        self.assertIn("preregistration_post_id", app1_data)

        # Check applicant data structure (should use SimpleAuthorSerializer)
        applicant_data = app1_data["applicant"]
        self.assertIn("id", applicant_data)
        self.assertIn("first_name", applicant_data)
        self.assertIn("last_name", applicant_data)

        # Verify application IDs are present
        application_ids = [app["id"] for app in applications]
        self.assertIn(application1.id, application_ids)
        self.assertIn(application2.id, application_ids)

        # Verify preregistration post IDs
        prereg_post_ids = [app["preregistration_post_id"] for app in applications]
        self.assertIn(prereg_post1.id, prereg_post_ids)
        self.assertIn(prereg_post2.id, prereg_post_ids)

    def test_serializes_non_grant_post_returns_none_for_grant(self):
        """Test that non-grant posts return None for the grant field"""
        # Use the existing discussion post from setUp
        serializer = PostSerializer(self.post)
        data = serializer.data

        # Verify grant field is None for non-grant posts
        self.assertIsNone(data["grant"])

    def test_serializes_grant_post_without_grant_returns_none(self):
        """Test that grant posts without actual Grant objects return None"""
        # Create a grant post but don't create an associated Grant object
        grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.GRANT,
        )

        grant_post = ResearchhubPost.objects.create(
            title="Grant Post Without Grant Object",
            created_by=self.user,
            document_type=document_type.GRANT,
            renderable_text="This grant post has no Grant object",
            unified_document=grant_unified_doc,
        )

        # Serialize the post
        serializer = PostSerializer(grant_post)
        data = serializer.data

        # Verify grant field is None when no Grant object exists
        self.assertIsNone(data["grant"])

    def test_serializes_expired_grant(self):
        """Test that expired grants are properly identified"""
        from datetime import datetime, timedelta

        import pytz

        # Create a grant post with an expired grant
        grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.GRANT,
        )

        grant_post = ResearchhubPost.objects.create(
            title="Expired Grant Post",
            created_by=self.user,
            document_type=document_type.GRANT,
            unified_document=grant_unified_doc,
        )

        # Create an expired grant (end_date in the past)
        past_date = datetime.now(pytz.UTC) - timedelta(days=5)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_unified_doc,
            amount=Decimal("15000.00"),
            currency="USD",
            organization="Expired Foundation",
            description="This grant has expired",
            status=Grant.OPEN,
            end_date=past_date,
        )

        # Get the context
        context = FeedViewMixin().get_common_serializer_context()

        # Serialize the grant post
        serializer = PostSerializer(grant_post, context=context)
        data = serializer.data

        # Verify grant data shows as expired and not active
        grant_data = data["grant"]
        self.assertEqual(grant_data["id"], grant.id)
        self.assertTrue(grant_data["is_expired"])
        self.assertFalse(grant_data["is_active"])

    def test_post_with_fundraise_no_user_recursion(self):
        """Test that posts with fundraises don't cause user serializer recursion"""
        # Create exchange rate for fundraise
        RscExchangeRate.objects.create(
            rate=0.01,
            real_rate=0.01,
        )

        # Create user with editor permissions
        editor_user = create_random_default_user("editor")

        # Create a hub and give editor permissions to the user
        hub = create_hub(name="Test Hub")
        hub_content_type = ContentType.objects.get_for_model(Hub)
        Permission.objects.create(
            user=editor_user,
            content_type=hub_content_type,
            object_id=hub.id,
            access_type="EDITOR",
        )

        # Create preregistration post
        preregistration_post = ResearchhubPost.objects.create(
            title="Test Preregistration with Fundraise",
            document_type=PREREGISTRATION,
            created_by=editor_user,
            unified_document=self.unified_document,
            renderable_text="Test content",
        )

        # Create fundraise
        fundraise = Fundraise.objects.create(
            unified_document=self.unified_document,
            created_by=editor_user,
            goal_amount=10000,
            goal_currency=USD,
            status="OPEN",
        )

        # Add contributor
        fundraise.purchases.create(
            user=self.user,
            amount=100,
            purchase_type="BOOST",
        )

        try:
            serializer = PostSerializer(preregistration_post)
            data = serializer.data

            # Verify fundraise data
            self.assertIn("fundraise", data)
            self.assertIsNotNone(data["fundraise"])

            # Verify user fields are limited (no editor_of)
            created_by = data["fundraise"]["created_by"]
            self.assertIn("id", created_by)
            self.assertIn("first_name", created_by)
            self.assertNotIn(
                "editor_of",
                created_by,
                "User should not have editor_of field to prevent recursion",
            )

            # Check contributors
            contributors = data["fundraise"]["contributors"]
            self.assertIsInstance(contributors, dict)
            self.assertIn("top", contributors)
            if contributors["top"]:
                contributor = contributors["top"][0]
                self.assertNotIn(
                    "editor_of",
                    contributor,
                    "Contributor should not have editor_of field",
                )

        except RecursionError:
            self.fail(
                "RecursionError was raised - user serializer circular "
                "reference fix failed"
            )

    def test_grant_post_no_user_recursion(self):
        """Test that grant posts don't cause user serializer recursion"""
        # Create exchange rate for grant
        RscExchangeRate.objects.create(
            rate=0.01,
            real_rate=0.01,
        )

        # Create user with editor permissions
        editor_user = create_random_default_user("grant_editor")

        # Create a hub and give editor permissions to the user
        hub = create_hub(name="Grant Hub")
        hub_content_type = ContentType.objects.get_for_model(Hub)
        Permission.objects.create(
            user=editor_user,
            content_type=hub_content_type,
            object_id=hub.id,
            access_type="EDITOR",
        )

        # Create grant post
        grant_post = ResearchhubPost.objects.create(
            title="Test Grant",
            document_type=GRANT,
            created_by=editor_user,
            unified_document=self.unified_document,
            renderable_text="Test grant content",
        )

        # Create grant
        grant = Grant.objects.create(
            unified_document=self.unified_document,
            created_by=editor_user,
            amount=50000,
            currency=USD,
            status="ACTIVE",
            organization="Test Foundation",
        )
        grant.contacts.add(editor_user)  # Add editor as contact

        try:
            serializer = PostSerializer(grant_post)
            data = serializer.data

            # Verify grant data
            self.assertIn("grant", data)
            self.assertIsNotNone(data["grant"])

            # Verify created_by user fields are limited (no editor_of)
            created_by = data["grant"]["created_by"]
            self.assertIn("id", created_by)
            self.assertIn("first_name", created_by)
            self.assertNotIn(
                "editor_of",
                created_by,
                "Created by user should not have editor_of field to prevent recursion",
            )

            # Check contacts
            contacts = data["grant"]["contacts"]
            self.assertTrue(contacts)  # Should have at least one contact
            contact = contacts[0]
            self.assertIn("id", contact)
            self.assertIn("first_name", contact)
            self.assertNotIn(
                "editor_of",
                contact,
                "Contact user should not have editor_of field to prevent recursion",
            )

        except RecursionError:
            self.fail(
                "RecursionError was raised - grant user serializer circular "
                "reference fix failed"
            )


class SimpleHubSerializerTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.hub = create_hub("Test Hub")

    def test_serializes_hub(self):
        serializer = SimpleHubSerializer(self.hub)
        data = serializer.data

        self.assertEqual(data["id"], self.hub.id)
        self.assertEqual(data["name"], self.hub.name)
        self.assertEqual(data["slug"], self.hub.slug)


class SimpleReviewSerializerTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("paper_creator")
        self.author = self.user.author_profile
        self.author.profile_image = "https://example.com/profile.jpg"
        self.author.save()

        self.paper = create_paper(
            uploaded_by=self.user,
            title="Test Paper",
            raw_authors=["Test Author", "Test Author 2"],
        )
        self.paper.authors.add(self.user.author_profile)
        self.paper.save()

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

        self.review = Review.objects.create(
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.paper.unified_document,
        )

    def test_serializes_review(self):
        # Act
        data = SimpleReviewSerializer(self.review).data

        # Assert
        self.assertEqual(data["id"], self.review.id)
        self.assertEqual(data["score"], self.review.score)
        self.assertIn("author", data)


@patch.object(Figure._meta.get_field("file"), "storage", test_storage)
@patch.object(Figure._meta.get_field("thumbnail"), "storage", test_storage)
class FeedEntrySerializerTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("feed_creator")

        return None

    def test_serializes_paper_feed_entry_with_unified_document_id(self):
        """Test that paper feed entries include unified_document_id in content_object"""
        paper = create_paper(uploaded_by=self.user)
        paper.score = 42
        paper.discussion_count = 15
        paper.save()

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

            # Verify basic feed entry fields
            self.assertIn("id", data)
            self.assertIn("content_type", data)
            self.assertEqual(data["content_type"], "PAPER")
            self.assertIn("content_object", data)

            # Verify unified_document_id is included in content_object
            paper_data = data["content_object"]
            self.assertIn("unified_document_id", paper_data)
            self.assertEqual(
                paper_data["unified_document_id"], paper.unified_document.id
            )

    def test_serializes_post_feed_entry_with_unified_document_id(self):
        """Test that post feed entries include unified_document_id in content_object"""
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

        # Verify unified_document_id is included in content_object
        post_data = data["content_object"]
        self.assertIn("unified_document_id", post_data)
        self.assertEqual(post_data["unified_document_id"], post.unified_document.id)

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
    def test_feed_entry_includes_purchases(self, mock_get_primary_hub):
        # Create a user and paper
        user = create_random_default_user("feed_purchase_test")
        paper = create_paper(uploaded_by=user, title="Test Paper with Purchases")

        # Create a hub and set it as primary
        hub = create_hub("Test Hub")
        mock_get_primary_hub.return_value = hub

        # Create a purchase for the unified document
        from purchase.models import Purchase

        purchase = Purchase.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="15.0",
            paid_status=Purchase.PAID,
        )

        # Create a feed entry
        feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            user=user,
            action="PUBLISH",
            action_date=paper.created_date,
            unified_document=paper.unified_document,
        )

        # Force an empty cache in the serializer
        feed_entry.content = {}
        feed_entry.save()

        # Serialize and check
        serializer = FeedEntrySerializer(feed_entry)
        data = serializer.data

        # Check that content_object contains the paper data including purchases
        self.assertIn("content_object", data)
        content_object = data["content_object"]

        # Verify the purchases are included in the serialized content
        self.assertIn("purchases", content_object)
        self.assertIsInstance(content_object["purchases"], list)
        self.assertEqual(len(content_object["purchases"]), 1)

        # Verify purchase data is correct
        purchase_data = content_object["purchases"][0]
        self.assertEqual(purchase_data["id"], purchase.id)
        self.assertEqual(purchase_data["amount"], purchase.amount)
        self.assertIn("user", purchase_data)

    def test_serializes_paper_feed_entry_primary_image(self):
        """Test that primary_image is correctly serialized in content_object."""
        paper = create_paper(uploaded_by=self.user)

        # Feed entry without primary image
        feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            item=paper,
            created_date=paper.created_date,
            action="PUBLISH",
            action_date=paper.created_date,
            user=self.user,
            unified_document=paper.unified_document,
        )

        serializer_no_image = FeedEntrySerializer(feed_entry)
        data_no_image = serializer_no_image.data
        self.assertIn("content_object", data_no_image)
        content_object_no_image = data_no_image["content_object"]
        self.assertIn("primary_image", content_object_no_image)
        self.assertIsNone(content_object_no_image["primary_image"])

        # Create a primary figure
        dummy_image = SimpleUploadedFile(
            "test_figure.jpg", b"file_content", content_type="image/jpeg"
        )
        primary_figure = Figure.objects.create(
            paper=paper,
            file=dummy_image,
            figure_type=Figure.FIGURE,
            is_primary=True,
        )

        # Re-serialize the same feed entry
        # (don't create a new one to avoid unique constraint)
        serializer_with_image = FeedEntrySerializer(feed_entry)
        data_with_image = serializer_with_image.data
        self.assertIn("content_object", data_with_image)
        content_object_with_image = data_with_image["content_object"]
        self.assertIn("primary_image", content_object_with_image)
        self.assertIsNotNone(content_object_with_image["primary_image"])
        self.assertEqual(
            content_object_with_image["primary_image"],
            default_storage.url(primary_figure.file.name),
        )

    def test_serializes_post_feed_entry_primary_image_returns_none(self):
        """Test that primary_image is not in content_object for posts."""
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.DISCUSSION,
        )

        post = ResearchhubPost.objects.create(
            title="Test Post",
            created_by=self.user,
            document_type=document_type.DISCUSSION,
            renderable_text="This is a test post",
            unified_document=unified_document,
        )

        feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            item=post,
            created_date=post.created_date,
            action="PUBLISH",
            action_date=post.created_date,
            user=self.user,
            unified_document=post.unified_document,
        )

        serializer = FeedEntrySerializer(feed_entry)
        data = serializer.data
        self.assertIn("content_object", data)
        content_object = data["content_object"]
        self.assertNotIn("primary_image", content_object)

    def test_paper_feed_entry_adds_missing_primary_image_keys(self):
        """Test that primary_image and primary_image_thumbnail are added as None
        when missing from pre-serialized content."""
        paper = create_paper(uploaded_by=self.user)

        # Create feed entry with pre-serialized content that's missing
        # primary_image and primary_image_thumbnail keys
        feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            item=paper,
            created_date=paper.created_date,
            action="PUBLISH",
            action_date=paper.created_date,
            user=self.user,
            unified_document=paper.unified_document,
            content={
                "id": paper.id,
                "title": paper.title,
                "abstract": paper.abstract,
                # Intentionally missing primary_image and primary_image_thumbnail
            },
        )

        serializer = FeedEntrySerializer(feed_entry)
        data = serializer.data

        self.assertIn("content_object", data)
        content_object = data["content_object"]

        # Verify that primary_image and primary_image_thumbnail are added as None
        self.assertIn("primary_image", content_object)
        self.assertIsNone(content_object["primary_image"])
        self.assertIn("primary_image_thumbnail", content_object)
        self.assertIsNone(content_object["primary_image_thumbnail"])

        # Verify other content is preserved
        self.assertEqual(content_object["id"], paper.id)
        self.assertEqual(content_object["title"], paper.title)

    def test_feed_entry_journal_handling_with_none(self):
        """Test journal handling when journal is None in pre-serialized content."""
        paper = create_paper(uploaded_by=self.user)
        journal_hub = create_hub("Test Journal", namespace=Hub.Namespace.JOURNAL)
        paper.hubs.add(journal_hub)
        paper.save()

        # Patch RESEARCHHUB_JOURNAL_ID to avoid ValueError when it's empty string
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", 999999):
            feed_entry = FeedEntry.objects.create(
                content_type=ContentType.objects.get_for_model(Paper),
                object_id=paper.id,
                item=paper,
                created_date=paper.created_date,
                action="PUBLISH",
                action_date=paper.created_date,
                user=self.user,
                unified_document=paper.unified_document,
                content={
                    "id": paper.id,
                    "title": paper.title,
                    "journal": None,  # journal is None
                },
            )

            serializer = FeedEntrySerializer(feed_entry)
            data = serializer.data
            content_object = data["content_object"]

            # Should apply journal shim when journal is None
            self.assertIn("journal", content_object)
            # Journal should be populated from unified_document
            self.assertIsNotNone(content_object["journal"])

    def test_feed_entry_journal_handling_with_dict_slug(self):
        """Test journal handling when journal is a dict with slug."""
        # Patch RESEARCHHUB_JOURNAL_ID to avoid ValueError when it's empty string
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", 999999):
            paper = create_paper(uploaded_by=self.user)

            # Test with preprint source (should not trigger shim)
            feed_entry_preprint = FeedEntry.objects.create(
                content_type=ContentType.objects.get_for_model(Paper),
                object_id=paper.id,
                item=paper,
                created_date=paper.created_date,
                action="PUBLISH",
                action_date=paper.created_date,
                user=self.user,
                unified_document=paper.unified_document,
                content={
                    "id": paper.id,
                    "title": paper.title,
                    "journal": {
                        "id": 1,
                        "name": "arXiv",
                        "slug": "arxiv",  # lowercase preprint source
                    },
                },
            )

            serializer_preprint = FeedEntrySerializer(feed_entry_preprint)
            data_preprint = serializer_preprint.data
            content_preprint = data_preprint["content_object"]

            # Should not trigger shim for preprint sources
            self.assertEqual(content_preprint["journal"]["slug"], "arxiv")

            # Test with non-preprint source (should trigger shim)
            # Create a new paper to avoid unique constraint violation
            paper_non_preprint = create_paper(uploaded_by=self.user)
            journal_hub = create_hub("Nature", namespace=Hub.Namespace.JOURNAL)
            paper_non_preprint.hubs.add(journal_hub)
            paper_non_preprint.save()

            feed_entry_non_preprint = FeedEntry.objects.create(
                content_type=ContentType.objects.get_for_model(Paper),
                object_id=paper_non_preprint.id,
                item=paper_non_preprint,
                created_date=paper_non_preprint.created_date,
                action="PUBLISH",
                action_date=paper_non_preprint.created_date,
                user=self.user,
                unified_document=paper_non_preprint.unified_document,
                content={
                    "id": paper_non_preprint.id,
                    "title": paper_non_preprint.title,
                    "journal": {
                        "id": 2,
                        "name": "Nature",
                        "slug": "nature",  # non-preprint source
                    },
                },
            )

            serializer_non_preprint = FeedEntrySerializer(feed_entry_non_preprint)
            data_non_preprint = serializer_non_preprint.data
            content_non_preprint = data_non_preprint["content_object"]

            # Should apply shim for non-preprint sources
            self.assertIn("journal", content_non_preprint)

    def test_feed_entry_journal_handling_with_dict_no_slug(self):
        """Test journal handling when journal is a dict without slug."""
        paper = create_paper(uploaded_by=self.user)
        journal_hub = create_hub("Test Journal", namespace=Hub.Namespace.JOURNAL)
        paper.hubs.add(journal_hub)
        paper.save()

        # Patch RESEARCHHUB_JOURNAL_ID to avoid ValueError when it's empty string
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", 999999):
            feed_entry = FeedEntry.objects.create(
                content_type=ContentType.objects.get_for_model(Paper),
                object_id=paper.id,
                item=paper,
                created_date=paper.created_date,
                action="PUBLISH",
                action_date=paper.created_date,
                user=self.user,
                unified_document=paper.unified_document,
                content={
                    "id": paper.id,
                    "title": paper.title,
                    "journal": {
                        "id": 1,
                        "name": "Test Journal",
                        # Missing slug key
                    },
                },
            )

            serializer = FeedEntrySerializer(feed_entry)
            data = serializer.data
            content_object = data["content_object"]

            # Should handle missing slug gracefully (defaults to empty string)
            # and trigger shim since empty string is not in PREPRINT_SOURCES
            self.assertIn("journal", content_object)

    def test_feed_entry_journal_handling_with_non_dict(self):
        """Test journal handling when journal is not a dict (e.g., string)."""
        paper = create_paper(uploaded_by=self.user)
        journal_hub = create_hub("Test Journal", namespace=Hub.Namespace.JOURNAL)
        paper.hubs.add(journal_hub)
        paper.save()

        # Patch RESEARCHHUB_JOURNAL_ID to avoid ValueError when it's empty string
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", 999999):
            feed_entry = FeedEntry.objects.create(
                content_type=ContentType.objects.get_for_model(Paper),
                object_id=paper.id,
                item=paper,
                created_date=paper.created_date,
                action="PUBLISH",
                action_date=paper.created_date,
                user=self.user,
                unified_document=paper.unified_document,
                content={
                    "id": paper.id,
                    "title": paper.title,
                    "journal": "some_string",  # journal is not a dict
                },
            )

            serializer = FeedEntrySerializer(feed_entry)
            data = serializer.data
            content_object = data["content_object"]

            # Should handle non-dict journal gracefully
            # isinstance(journal, dict) will be False, so journal_slug will be None
            # This should trigger shim since journal is not None but
            # journal_slug is None
            self.assertIn("journal", content_object)

    def test_feed_entry_journal_handling_with_uppercase_slug(self):
        """Test journal handling when journal slug is uppercase."""
        paper = create_paper(uploaded_by=self.user)

        feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            item=paper,
            created_date=paper.created_date,
            action="PUBLISH",
            action_date=paper.created_date,
            user=self.user,
            unified_document=paper.unified_document,
            content={
                "id": paper.id,
                "title": paper.title,
                "journal": {
                    "id": 1,
                    "name": "arXiv",
                    "slug": "ARXIV",  # uppercase slug
                },
            },
        )

        serializer = FeedEntrySerializer(feed_entry)
        data = serializer.data
        content_object = data["content_object"]

        # Slug should be lowercased for comparison
        # "arxiv" (lowercase) is in PREPRINT_SOURCES, so should not trigger shim
        self.assertIn("journal", content_object)
        # The original uppercase slug should be preserved in content
        self.assertEqual(content_object["journal"]["slug"], "ARXIV")


class FundingFeedEntrySerializerTests(AWSMockTestCase):
    """Test cases for the FundingFeedEntrySerializer"""

    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("funding_feed_user")

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_funding_feed_entry_serializer(self, mock_usd_to_rsc):
        """Test the FundingFeedEntrySerializer with and without nonprofit links"""
        # Mock the exchange rate conversion to avoid database dependency
        mock_usd_to_rsc.return_value = 200.0

        # Create a post for fundraising
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.PREREGISTRATION,
        )

        post = ResearchhubPost.objects.create(
            title="Fundraising Post",
            created_by=self.user,
            document_type=document_type.PREREGISTRATION,
            renderable_text="This is a fundraising post",
            unified_document=unified_doc,
        )

        # Create a fundraise without nonprofit links
        fundraise = Fundraise.objects.create(
            unified_document=unified_doc,
            created_by=self.user,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Create a feed entry for this fundraise
        feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            user=self.user,
            action="PUBLISH",
            action_date=post.created_date,
            unified_document=unified_doc,
        )

        # Test serialization without nonprofit links
        serializer = FundingFeedEntrySerializer(feed_entry)
        data = serializer.data

        # Verify basic feed entry fields
        self.assertIn("id", data)
        self.assertIn("content_type", data)
        self.assertEqual(data["content_type"], "RESEARCHHUBPOST")

        # Verify is_nonprofit field is present and False (no nonprofit links)
        self.assertIn("is_nonprofit", data)
        self.assertFalse(data["is_nonprofit"])

        # Create a nonprofit organization and link it to the fundraise
        nonprofit = NonprofitOrg.objects.create(name="Test Nonprofit")

        # Create the nonprofit link - variable not directly used but needed for test
        # Creating the link is necessary for the test though the variable isn't used
        NonprofitFundraiseLink.objects.create(fundraise=fundraise, nonprofit=nonprofit)

        # Re-serialize and verify is_nonprofit is now True
        serializer = FundingFeedEntrySerializer(feed_entry)
        data = serializer.data
        self.assertTrue(data["is_nonprofit"])
        data = serializer.data
        self.assertTrue(data["is_nonprofit"])
        data = serializer.data
        self.assertTrue(data["is_nonprofit"])
