"""
Unit tests for personalize_item_utils.

Tests text cleaning, hub mapping, and metrics extraction functions.
"""

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from analytics.services.personalize_item_utils import (
    clean_text_for_csv,
    get_author_ids,
    get_bounty_metrics,
    get_hub_mapping,
    get_last_comment_timestamp,
    get_proposal_metrics,
    get_rfp_metrics,
    load_item_ids_from_interactions,
)
from hub.models import Hub
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from purchase.models import Fundraise, Grant, GrantApplication
from reputation.models import Bounty, BountySolution, Escrow
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from user.models import User
from user.related_models.author_model import Author


class CleanTextForCSVTest(TestCase):
    """Test text cleaning for CSV safety."""

    def test_clean_text_strips_html(self):
        """Test that HTML tags are stripped."""
        text = "<p>Hello <strong>world</strong>!</p>"
        result = clean_text_for_csv(text)
        self.assertEqual(result, "Hello world!")

    def test_clean_text_removes_newlines(self):
        """Test that newlines are replaced with spaces."""
        text = "Line 1\nLine 2\rLine 3"
        result = clean_text_for_csv(text)
        self.assertEqual(result, "Line 1 Line 2 Line 3")

    def test_clean_text_removes_tabs(self):
        """Test that tabs are replaced with spaces."""
        text = "Column1\tColumn2\tColumn3"
        result = clean_text_for_csv(text)
        self.assertEqual(result, "Column1 Column2 Column3")

    def test_clean_text_collapses_spaces(self):
        """Test that multiple spaces are collapsed."""
        text = "Too   many    spaces"
        result = clean_text_for_csv(text)
        self.assertEqual(result, "Too many spaces")

    def test_clean_text_truncates_long_text(self):
        """Test that very long text is truncated."""
        text = "A" * 20000
        result = clean_text_for_csv(text)
        self.assertEqual(len(result), 10000)

    def test_clean_text_handles_none(self):
        """Test that None input returns None."""
        result = clean_text_for_csv(None)
        self.assertIsNone(result)

    def test_clean_text_handles_empty_string(self):
        """Test that empty string returns None."""
        result = clean_text_for_csv("")
        self.assertIsNone(result)


class GetHubMappingTest(TestCase):
    """Test hub mapping extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.hub1 = Hub.objects.create(name="Computer Science", slug="computer-science")
        self.hub2 = Hub.objects.create(name="Machine Learning", slug="machine-learning")

        self.user = User.objects.create(email="test@example.com", username="testuser")

    def test_get_hub_mapping_with_category_hub(self):
        """Test hub mapping uses category hub for L1."""
        # Create a unified document with a category hub
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        self.hub1.namespace = Hub.Namespace.CATEGORY
        self.hub1.save()
        unified_doc.hubs.add(self.hub1)

        paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=unified_doc
        )

        hub_l1, hub_l2 = get_hub_mapping(unified_doc, paper)

        # Should return the category hub ID as L1, L2 should be None
        self.assertEqual(hub_l1, str(self.hub1.id))
        self.assertIsNone(hub_l2)

    def test_get_hub_mapping_no_hubs(self):
        """Test hub mapping when no hubs are assigned."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=unified_doc
        )

        hub_l1, hub_l2 = get_hub_mapping(unified_doc, paper)

        self.assertIsNone(hub_l1)
        self.assertIsNone(hub_l2)

    def test_get_hub_mapping_with_category_and_subcategory(self):
        """Test hub mapping with both category and subcategory hubs."""
        # Create a unified document with both category and subcategory hubs
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Set up category hub
        self.hub1.namespace = Hub.Namespace.CATEGORY
        self.hub1.save()

        # Set up subcategory hub
        self.hub2.namespace = Hub.Namespace.SUBCATEGORY
        self.hub2.save()

        unified_doc.hubs.add(self.hub1, self.hub2)

        paper = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
        )

        hub_l1, hub_l2 = get_hub_mapping(unified_doc, paper)

        # Should return category hub ID as L1 and subcategory hub ID as L2
        self.assertEqual(hub_l1, str(self.hub1.id))
        self.assertEqual(hub_l2, str(self.hub2.id))

    def test_get_hub_mapping_with_subcategory_only(self):
        """Test hub mapping with only subcategory hub."""
        # Create a unified document with only subcategory hub
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Set up subcategory hub
        self.hub2.namespace = Hub.Namespace.SUBCATEGORY
        self.hub2.save()

        unified_doc.hubs.add(self.hub2)

        paper = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
        )

        hub_l1, hub_l2 = get_hub_mapping(unified_doc, paper)

        # Should return None for L1 and subcategory hub ID as L2
        self.assertIsNone(hub_l1)
        self.assertEqual(hub_l2, str(self.hub2.id))


class GetAuthorIDsTest(TestCase):
    """Test author ID extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

    def test_get_author_ids_for_post(self):
        """Test getting author ID for a post with authors ManyToMany."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )

        # Create additional users and authors
        user2 = User.objects.create(email="author2@example.com", username="author2")
        author1, _ = Author.objects.get_or_create(
            user=self.user, defaults={"first_name": "Test", "last_name": "Author"}
        )
        author2, _ = Author.objects.get_or_create(
            user=user2, defaults={"first_name": "Test2", "last_name": "Author2"}
        )

        post = ResearchhubPost.objects.create(
            title="Test Post", created_by=self.user, unified_document=unified_doc
        )
        # Add authors via ManyToMany
        post.authors.add(author1, author2)

        result = get_author_ids(unified_doc, post)

        # Should return the authors from ManyToMany field
        self.assertIsNotNone(result)
        author_ids = result.split(",")
        self.assertEqual(len(author_ids), 2)
        self.assertIn(str(author1.id), author_ids)
        self.assertIn(str(author2.id), author_ids)

    def test_get_author_ids_for_post_with_empty_authors(self):
        """Test post with no authors falls back to created_by."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )

        post = ResearchhubPost.objects.create(
            title="Test Post", created_by=self.user, unified_document=unified_doc
        )
        # Don't add any authors - should fallback to created_by

        result = get_author_ids(unified_doc, post)

        # Should return the created_by author profile ID
        self.assertIsNotNone(result)
        self.assertEqual(result, str(self.user.author_profile.id))

    def test_get_author_ids_for_preregistration(self):
        """Test getting author IDs for a PREREGISTRATION document type."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION"
        )

        # Create additional users and authors
        user2 = User.objects.create(email="author2@example.com", username="author2")
        author1, _ = Author.objects.get_or_create(
            user=self.user, defaults={"first_name": "Test", "last_name": "Author"}
        )
        author2, _ = Author.objects.get_or_create(
            user=user2, defaults={"first_name": "Test2", "last_name": "Author2"}
        )

        post = ResearchhubPost.objects.create(
            title="Test Preregistration",
            document_type="PREREGISTRATION",
            created_by=self.user,
            unified_document=unified_doc,
        )
        # Add authors via ManyToMany
        post.authors.add(author1, author2)

        result = get_author_ids(unified_doc, post)

        # Should return the authors from ManyToMany field
        self.assertIsNotNone(result)
        author_ids = result.split(",")
        self.assertEqual(len(author_ids), 2)
        self.assertIn(str(author1.id), author_ids)
        self.assertIn(str(author2.id), author_ids)

    def test_get_author_ids_for_paper_with_authorships(self):
        """Test getting author IDs for a paper with authorships."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Create additional users and authors
        user2 = User.objects.create(email="author2@example.com", username="author2")
        author1, _ = Author.objects.get_or_create(
            user=self.user,
            defaults={"first_name": "Test", "last_name": "Author", "claimed": True},
        )
        author2, _ = Author.objects.get_or_create(
            user=user2,
            defaults={"first_name": "Test2", "last_name": "Author2", "claimed": True},
        )

        paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=unified_doc
        )

        # Create authorships
        Authorship.objects.create(paper=paper, author=author1)
        Authorship.objects.create(paper=paper, author=author2)

        result = get_author_ids(unified_doc, paper)

        # Should return the authors from authorships
        self.assertIsNotNone(result)
        author_ids = result.split(",")
        self.assertEqual(len(author_ids), 2)
        self.assertIn(str(author1.id), author_ids)
        self.assertIn(str(author2.id), author_ids)

    def test_get_author_ids_for_paper_without_authorships(self):
        """Test paper without authorships falls back to raw_authors."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Create an author that will be matched from raw_authors
        author, created = Author.objects.get_or_create(
            user=self.user,
            defaults={
                "first_name": "Test",
                "last_name": "Author",
                "claimed": True,
                "orcid_id": "0000-0000-0000-0001",
            },
        )

        # If author already exists, update the ORCID ID
        if not created:
            author.orcid_id = "0000-0000-0000-0001"
            author.claimed = True
            author.save()

        paper = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
            raw_authors=[
                {
                    "first_name": "Test",
                    "last_name": "Author",
                    "orcid": "https://orcid.org/0000-0000-0000-0001",
                }
            ],
        )
        # Don't create any authorships - should fallback to raw_authors

        result = get_author_ids(unified_doc, paper)

        # Should return the author from raw_authors matching
        self.assertIsNotNone(result)
        self.assertEqual(result, str(author.id))

    def test_get_author_ids_for_grant(self):
        """Test getting author IDs for a GRANT document from grant's contacts."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="GRANT")

        # Create a post for the grant (but post's created_by should be ignored)
        different_user = User.objects.create(
            email="different@example.com", username="differentuser"
        )
        post = ResearchhubPost.objects.create(
            title="Test Grant",
            document_type="GRANT",
            created_by=different_user,
            unified_document=unified_doc,
        )

        # Create additional contact users
        contact_user1 = User.objects.create(
            email="contact1@example.com", username="contact1"
        )
        contact_user2 = User.objects.create(
            email="contact2@example.com", username="contact2"
        )

        # Create grant with the main user as creator
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=unified_doc,
            amount=5000.00,
            currency="USD",
            description="Test grant",
            status=Grant.OPEN,
        )

        # Add contacts to the grant
        grant.contacts.add(contact_user1, contact_user2)

        result = get_author_ids(unified_doc, post)

        # Should return the grant contacts' author profile IDs, not post's created_by
        self.assertIsNotNone(result)
        author_ids = result.split(",")
        self.assertEqual(len(author_ids), 2)
        self.assertIn(str(contact_user1.author_profile.id), author_ids)
        self.assertIn(str(contact_user2.author_profile.id), author_ids)

    def test_get_author_ids_for_grant_no_contacts(self):
        """Test getting author IDs for a GRANT document with no contacts."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="GRANT")

        # Need to create a user for the post's created_by
        post_user = User.objects.create(
            email="postuser@example.com", username="postuser"
        )

        post = ResearchhubPost.objects.create(
            title="Test Grant",
            document_type="GRANT",
            created_by=post_user,
            unified_document=unified_doc,
        )

        # Create grant with no contacts
        Grant.objects.create(
            created_by=self.user,
            unified_document=unified_doc,
            amount=5000.00,
            currency="USD",
            description="Test grant",
            status=Grant.OPEN,
        )

        result = get_author_ids(unified_doc, post)

        # Should return None when no contacts are set
        self.assertIsNone(result)

    def test_get_author_ids_for_paper_with_raw_authors_orcid(self):
        """Test getting author IDs for a paper using raw_authors with ORCID matching."""
        from user.related_models.author_model import Author

        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Create an author with ORCID
        author = Author.objects.create(
            first_name="John",
            last_name="Doe",
            claimed=True,
            orcid_id="https://orcid.org/0000-0001-2345-6789",
        )

        # Create paper with raw_authors (no authorships or authors)
        paper = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
            raw_authors=[
                {
                    "orcid": "https://orcid.org/0000-0001-2345-6789",
                    "first_name": "John",
                    "last_name": "Doe",
                    "open_alex_id": "https://openalex.org/A123456",
                }
            ],
        )

        result = get_author_ids(unified_doc, paper)

        # Should extract author ID from raw_authors using ORCID
        self.assertIsNotNone(result)
        self.assertEqual(result, str(author.id))

    def test_get_author_ids_for_paper_with_raw_authors_openalex(self):
        """Test getting author IDs using raw_authors with OpenAlex ID."""
        from user.related_models.author_model import Author

        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Create an author with OpenAlex ID (no ORCID)
        author = Author.objects.create(
            first_name="Jane",
            last_name="Smith",
            claimed=True,
            openalex_ids=["https://openalex.org/A987654"],
        )

        # Create paper with raw_authors (no ORCID)
        paper = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
            raw_authors=[
                {
                    "orcid": None,
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "open_alex_id": "https://openalex.org/A987654",
                }
            ],
        )

        result = get_author_ids(unified_doc, paper)

        # Should extract author ID from raw_authors using OpenAlex ID
        self.assertIsNotNone(result)
        self.assertEqual(result, str(author.id))

    def test_get_author_ids_for_paper_filters_unclaimed_from_raw_authors(self):
        """Test that unclaimed authors are filtered out when using raw_authors."""
        from user.related_models.author_model import Author

        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Create an unclaimed author
        Author.objects.create(
            first_name="Unclaimed",
            last_name="Author",
            claimed=False,
            orcid_id="https://orcid.org/0000-0001-1111-1111",
        )

        # Create paper with raw_authors
        paper = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
            raw_authors=[
                {
                    "orcid": "https://orcid.org/0000-0001-1111-1111",
                    "first_name": "Unclaimed",
                    "last_name": "Author",
                }
            ],
        )

        result = get_author_ids(unified_doc, paper)

        # Should return None since author is unclaimed
        self.assertIsNone(result)

    def test_get_author_ids_no_author(self):
        """Test getting author IDs when there are none."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Create paper with no authors, authorships, or raw_authors
        paper = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
            raw_authors=None,
        )

        result = get_author_ids(unified_doc, paper)
        self.assertIsNone(result)


class GetBountyMetricsTest(TestCase):
    """Test bounty metrics extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="QUESTION"
        )

        self.paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=self.unified_doc
        )

    def test_get_bounty_metrics_with_open_bounty(self):
        """Test getting bounty metrics with an open bounty."""
        content_type = ContentType.objects.get_for_model(Paper)
        expiration_date = timezone.now() + timedelta(days=30)

        # Create escrow first with temporary object_id
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=100,
            content_type=ContentType.objects.get_for_model(Bounty),
            object_id=1,  # Temporary, will be updated
        )

        # Create bounty with escrow
        bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=escrow,
            amount=100,
            status=Bounty.OPEN,
            expiration_date=expiration_date,
            item_content_type=content_type,
            item_object_id=self.paper.id,
            unified_document=self.unified_doc,
        )

        # Update escrow's object_id to point to the bounty
        escrow.object_id = bounty.id
        escrow.save()

        # Create a solution
        BountySolution.objects.create(
            bounty=bounty,
            created_by=self.user,
            status=BountySolution.Status.SUBMITTED,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
        )

        metrics = get_bounty_metrics(self.unified_doc)

        self.assertEqual(metrics["BOUNTY_AMOUNT"], 100.0)
        self.assertIsNotNone(metrics["BOUNTY_EXPIRES_AT"])
        self.assertEqual(metrics["BOUNTY_NUM_OF_SOLUTIONS"], 1)

    def test_get_bounty_metrics_no_bounty(self):
        """Test getting bounty metrics when there are no bounties."""
        metrics = get_bounty_metrics(self.unified_doc)

        self.assertIsNone(metrics["BOUNTY_AMOUNT"])
        self.assertIsNone(metrics["BOUNTY_EXPIRES_AT"])
        self.assertIsNone(metrics["BOUNTY_NUM_OF_SOLUTIONS"])


class GetProposalMetricsTest(TestCase):
    """Test proposal (fundraise) metrics extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION"
        )

    def test_get_proposal_metrics_with_fundraise(self):
        """Test getting proposal metrics with an open fundraise."""
        # Create escrow for fundraise with temporary object_id
        fundraise_ct = ContentType.objects.get_for_model(Fundraise)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=500,
            content_type=fundraise_ct,
            object_id=1,  # Temporary, will be updated
        )

        # Create fundraise
        end_date = timezone.now() + timedelta(days=30)
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            escrow=escrow,
            status=Fundraise.OPEN,
            goal_amount=1000,
            end_date=end_date,
        )

        # Update escrow's object_id to point to fundraise
        escrow.object_id = fundraise.id
        escrow.save()

        metrics = get_proposal_metrics(self.unified_doc)

        self.assertEqual(metrics["PROPOSAL_AMOUNT"], 1000.0)
        self.assertIsNotNone(metrics["PROPOSAL_EXPIRES_AT"])
        self.assertEqual(metrics["PROPOSAL_NUM_OF_FUNDERS"], 0)

    def test_get_proposal_metrics_with_closed_fundraise(self):
        """Test getting proposal metrics with a closed fundraise."""
        # Create escrow for fundraise with temporary object_id
        fundraise_ct = ContentType.objects.get_for_model(Fundraise)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=500,
            content_type=fundraise_ct,
            object_id=1,  # Temporary, will be updated
        )

        # Create CLOSED fundraise
        end_date = timezone.now() + timedelta(days=30)
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            escrow=escrow,
            status=Fundraise.CLOSED,
            goal_amount=2000,
            end_date=end_date,
        )

        # Update escrow's object_id to point to fundraise
        escrow.object_id = fundraise.id
        escrow.save()

        metrics = get_proposal_metrics(self.unified_doc)

        # Should still get metrics even though status is CLOSED
        self.assertEqual(metrics["PROPOSAL_AMOUNT"], 2000.0)
        self.assertIsNotNone(metrics["PROPOSAL_EXPIRES_AT"])
        self.assertEqual(metrics["PROPOSAL_NUM_OF_FUNDERS"], 0)

    def test_get_proposal_metrics_no_fundraise(self):
        """Test getting proposal metrics when there are no fundraises."""
        metrics = get_proposal_metrics(self.unified_doc)

        self.assertIsNone(metrics["PROPOSAL_AMOUNT"])
        self.assertIsNone(metrics["PROPOSAL_EXPIRES_AT"])
        self.assertIsNone(metrics["PROPOSAL_NUM_OF_FUNDERS"])


class GetRFPMetricsTest(TestCase):
    """Test RFP metrics extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="GRANT"
        )

        self.post = ResearchhubPost.objects.create(
            title="Test Grant",
            document_type="GRANT",
            created_by=self.user,
            unified_document=self.unified_doc,
        )

    def test_get_rfp_metrics_with_applications(self):
        """Test getting RFP metrics with grant applications."""
        # Create grant
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            amount=10000.00,
            currency="USD",
            description="Test grant",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )

        # Create grant applications with different posts
        post2 = ResearchhubPost.objects.create(
            title="Test Grant 2",
            document_type="GRANT",
            created_by=self.user,
            unified_document=self.unified_doc,
        )
        GrantApplication.objects.create(
            grant=grant, applicant=self.user, preregistration_post=self.post
        )
        GrantApplication.objects.create(
            grant=grant, applicant=self.user, preregistration_post=post2
        )

        metrics = get_rfp_metrics(self.unified_doc)

        self.assertEqual(metrics["REQUEST_FOR_PROPOSAL_AMOUNT"], 10000.00)
        self.assertIsNotNone(metrics["REQUEST_FOR_PROPOSAL_EXPIRES_AT"])
        self.assertEqual(metrics["REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS"], 2)

    def test_get_rfp_metrics_with_closed_grant(self):
        """Test getting RFP metrics with a closed grant."""
        # Create CLOSED grant
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            amount=7500.00,
            currency="USD",
            description="Test closed grant",
            status=Grant.CLOSED,
            end_date=timezone.now() + timedelta(days=15),
        )

        # Create grant application
        GrantApplication.objects.create(
            grant=grant, applicant=self.user, preregistration_post=self.post
        )

        metrics = get_rfp_metrics(self.unified_doc)

        # Should still get metrics even though status is CLOSED
        self.assertEqual(metrics["REQUEST_FOR_PROPOSAL_AMOUNT"], 7500.00)
        self.assertIsNotNone(metrics["REQUEST_FOR_PROPOSAL_EXPIRES_AT"])
        self.assertEqual(metrics["REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS"], 1)

    def test_get_rfp_metrics_no_applications(self):
        """Test getting RFP metrics when there are no applications."""
        metrics = get_rfp_metrics(self.unified_doc)

        self.assertIsNone(metrics["REQUEST_FOR_PROPOSAL_AMOUNT"])
        self.assertIsNone(metrics["REQUEST_FOR_PROPOSAL_EXPIRES_AT"])
        self.assertEqual(metrics["REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS"], 0)


class GetLastCommentTimestampTest(TestCase):
    """Test last comment timestamp extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )

        self.paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=self.unified_doc
        )

    def test_get_last_comment_timestamp_with_comments(self):
        """Test getting last comment timestamp when comments exist."""
        # Create a thread
        content_type = ContentType.objects.get_for_model(Paper)
        thread = RhCommentThreadModel.objects.create(
            content_type=content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )

        # Create comments
        RhCommentModel.objects.create(
            thread=thread, created_by=self.user, updated_by=self.user
        )

        # Create a newer comment
        RhCommentModel.objects.create(
            thread=thread, created_by=self.user, updated_by=self.user
        )

        timestamp = get_last_comment_timestamp(self.unified_doc)

        self.assertIsNotNone(timestamp)
        self.assertIsInstance(timestamp, int)

    def test_get_last_comment_timestamp_no_comments(self):
        """Test getting last comment timestamp when there are no comments."""
        timestamp = get_last_comment_timestamp(self.unified_doc)
        self.assertIsNone(timestamp)


class LoadItemIdsFromInteractionsTest(TestCase):
    """Test loading item IDs from interactions."""

    def setUp(self):
        """Set up test fixtures."""
        import os
        import tempfile

        # Create temporary directory for test files
        self.test_dir = tempfile.mkdtemp()
        self.interactions_path = os.path.join(self.test_dir, "interactions.csv")
        self.cache_path = self.interactions_path.replace(".csv", ".item_ids.cache")

    def tearDown(self):
        """Clean up test files."""
        import shutil

        if hasattr(self, "test_dir"):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_from_cache_file(self):
        """Test loading item IDs from cache file."""
        # Write cache file
        with open(self.cache_path, "w", encoding="utf-8") as f:
            f.write("1\n2\n3\n5\n10\n")

        item_ids = load_item_ids_from_interactions(self.interactions_path)

        self.assertEqual(item_ids, {1, 2, 3, 5, 10})

    def test_load_from_csv_file(self):
        """Test loading item IDs from CSV file when cache doesn't exist."""
        import csv

        # Write interactions CSV
        with open(self.interactions_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["USER_ID", "ITEM_ID", "TIMESTAMP"])
            writer.writeheader()
            writer.writerow({"USER_ID": "1", "ITEM_ID": "10", "TIMESTAMP": "123456"})
            writer.writerow({"USER_ID": "2", "ITEM_ID": "20", "TIMESTAMP": "123457"})
            writer.writerow({"USER_ID": "1", "ITEM_ID": "10", "TIMESTAMP": "123458"})
            writer.writerow({"USER_ID": "3", "ITEM_ID": "30", "TIMESTAMP": "123459"})

        item_ids = load_item_ids_from_interactions(self.interactions_path)

        # Should deduplicate - only unique IDs
        self.assertEqual(item_ids, {10, 20, 30})

    def test_load_prefers_cache_over_csv(self):
        """Test that cache file is preferred over CSV."""
        import csv

        # Write both cache and CSV with different data
        with open(self.cache_path, "w", encoding="utf-8") as f:
            f.write("100\n200\n")

        with open(self.interactions_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["USER_ID", "ITEM_ID", "TIMESTAMP"])
            writer.writeheader()
            writer.writerow({"USER_ID": "1", "ITEM_ID": "999", "TIMESTAMP": "123456"})

        item_ids = load_item_ids_from_interactions(self.interactions_path)

        # Should use cache file data
        self.assertEqual(item_ids, {100, 200})

    def test_load_file_not_found(self):
        """Test error when neither cache nor CSV exists."""
        with self.assertRaises(FileNotFoundError):
            load_item_ids_from_interactions(self.interactions_path)

    def test_load_handles_empty_lines(self):
        """Test that empty lines in cache are skipped."""
        # Write cache with empty lines
        with open(self.cache_path, "w", encoding="utf-8") as f:
            f.write("1\n\n2\n  \n3\n")

        item_ids = load_item_ids_from_interactions(self.interactions_path)

        self.assertEqual(item_ids, {1, 2, 3})
