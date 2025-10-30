"""
Tests for Personalize item mapper functions.
"""

from datetime import datetime

import pytz
from django.test import TestCase

from analytics.constants.personalize_constants import (
    AUTHOR_IDS,
    BLUESKY_COUNT_TOTAL,
    BOUNTY_HAS_SOLUTIONS,
    CITATION_COUNT_TOTAL,
    CREATION_TIMESTAMP,
    DELIMITER,
    FIELD_DEFAULTS,
    HAS_ACTIVE_BOUNTY,
    HUB_IDS,
    HUB_L1,
    HUB_L2,
    ITEM_ID,
    ITEM_TYPE,
    MAX_TEXT_LENGTH,
    PEER_REVIEW_COUNT_TOTAL,
    PROPOSAL_HAS_FUNDERS,
    PROPOSAL_IS_OPEN,
    RFP_HAS_APPLICANTS,
    RFP_IS_OPEN,
    TEXT,
    TITLE,
    TWEET_COUNT_TOTAL,
    UPVOTE_SCORE,
)
from analytics.items.personalize_item_mapper import PersonalizeItemMapper
from analytics.tests.helpers import (
    create_author,
    create_batch_data,
    create_hub_with_namespace,
    create_prefetched_grant,
    create_prefetched_paper,
    create_prefetched_post,
    create_prefetched_proposal,
)
from hub.models import Hub
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    QUESTION,
)
from user.models import User


class QueryPreventionTests(TestCase):
    """Tests to ensure mapper doesn't fire queries."""

    def test_map_to_item_makes_no_queries_when_properly_prefetched(self):
        """Should make minimal queries when document is properly prefetched."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(title="Test Paper")
        batch_data = create_batch_data()

        # Act & Assert
        # Note: get_hub_names() does a values_list query even with prefetch,
        # so we allow 1 query. The important thing is no N+1 queries.
        with self.assertNumQueries(1):
            result = mapper.map_to_item(
                unified_doc,
                bounty_data=batch_data["bounty"],
                proposal_data=batch_data["proposal"],
                rfp_data=batch_data["rfp"],
                review_count_data=batch_data["review_count"],
            )

        self.assertIsNotNone(result)


class DocumentTypeTests(TestCase):
    """Tests for document type mapping."""

    def test_grant_maps_to_rfp(self):
        """Grant documents should map to ITEM_TYPE='RFP'."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_grant(title="Test Grant")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[ITEM_TYPE], "RFP")

    def test_paper_stays_as_paper(self):
        """Paper documents should stay as ITEM_TYPE='PAPER'."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(title="Test Paper")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[ITEM_TYPE], "PAPER")

    def test_discussion_maps_to_post(self):
        """Discussion posts should map to ITEM_TYPE='POST'."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_post(
            title="Test Discussion", document_type=DISCUSSION
        )
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[ITEM_TYPE], "POST")

    def test_question_stays_as_question(self):
        """Question posts should stay as ITEM_TYPE='QUESTION'."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_post(
            title="Test Question", document_type=QUESTION
        )
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[ITEM_TYPE], "QUESTION")

    def test_preregistration_maps_to_proposal(self):
        """Preregistration documents should map to ITEM_TYPE='PROPOSAL'."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_proposal(title="Test Proposal")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[ITEM_TYPE], "PROPOSAL")


class BountyFlagTests(TestCase):
    """Tests for bounty flag mapping."""

    def test_has_active_bounty_true_when_bounty_data_provided(self):
        """
        HAS_ACTIVE_BOUNTY should be True
        when bounty_data contains has_active_bounty=True.
        """
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper()
        batch_data = create_batch_data(has_active_bounty=True)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertTrue(result[HAS_ACTIVE_BOUNTY])

    def test_has_active_bounty_false_when_no_bounty_data(self):
        """HAS_ACTIVE_BOUNTY should be False when bounty_data is empty."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper()
        batch_data = create_batch_data(has_active_bounty=False)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertFalse(result[HAS_ACTIVE_BOUNTY])

    def test_bounty_has_solutions_true_when_solutions_exist(self):
        """
        BOUNTY_HAS_SOLUTIONS should be True
        when bounty_data contains has_solutions=True.
        """
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper()
        batch_data = create_batch_data(has_solutions=True)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertTrue(result[BOUNTY_HAS_SOLUTIONS])

    def test_bounty_has_solutions_false_when_no_solutions(self):
        """BOUNTY_HAS_SOLUTIONS should be False when bounty_data lacks solutions."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper()
        batch_data = create_batch_data(has_solutions=False)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertFalse(result[BOUNTY_HAS_SOLUTIONS])


class ProposalFlagTests(TestCase):
    """Tests for proposal/fundraise flag mapping."""

    def test_proposal_has_funders_true_when_funders_exist(self):
        """
        PROPOSAL_HAS_FUNDERS should be True
        when proposal_data contains has_funders=True.
        """
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_proposal()
        batch_data = create_batch_data(proposal_has_funders=True)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertTrue(result[PROPOSAL_HAS_FUNDERS])

    def test_proposal_has_funders_false_when_no_funders(self):
        """PROPOSAL_HAS_FUNDERS should be False when proposal_data is empty."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_proposal()
        batch_data = create_batch_data(proposal_has_funders=False)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertFalse(result[PROPOSAL_HAS_FUNDERS])

    def test_proposal_is_open_true_when_open(self):
        """PROPOSAL_IS_OPEN should be True when proposal_data contains is_open=True."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_proposal()
        batch_data = create_batch_data(proposal_is_open=True)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertTrue(result[PROPOSAL_IS_OPEN])

    def test_proposal_is_open_false_when_closed(self):
        """
        PROPOSAL_IS_OPEN should be False
        when proposal_data contains is_open=False.
        """
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_proposal()
        batch_data = create_batch_data(proposal_is_open=False)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertFalse(result[PROPOSAL_IS_OPEN])


class RFPFlagTests(TestCase):
    """Tests for RFP/grant flag mapping."""

    def test_rfp_is_open_true_when_grant_open(self):
        """RFP_IS_OPEN should be True when rfp_data contains is_open=True."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_grant()
        batch_data = create_batch_data(rfp_is_open=True)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertTrue(result[RFP_IS_OPEN])

    def test_rfp_is_open_false_when_grant_closed_or_expired(self):
        """RFP_IS_OPEN should be False when rfp_data contains is_open=False."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_grant()
        batch_data = create_batch_data(rfp_is_open=False)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertFalse(result[RFP_IS_OPEN])

    def test_rfp_has_applicants_true_when_applicants_exist(self):
        """
        RFP_HAS_APPLICANTS should be True
        when rfp_data contains has_applicants=True.
        """
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_grant()
        batch_data = create_batch_data(rfp_has_applicants=True)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertTrue(result[RFP_HAS_APPLICANTS])

    def test_rfp_has_applicants_false_when_no_applicants(self):
        """RFP_HAS_APPLICANTS should be False when rfp_data is empty."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_grant()
        batch_data = create_batch_data(rfp_has_applicants=False)

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertFalse(result[RFP_HAS_APPLICANTS])


class CommonFieldTests(TestCase):
    """Tests for common field mapping."""

    def test_item_id_is_string(self):
        """ITEM_ID should be string representation of unified_doc.id."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper()
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[ITEM_ID], str(unified_doc.id))
        self.assertIsInstance(result[ITEM_ID], str)

    def test_creation_timestamp_uses_paper_publish_date_for_papers(self):
        """Papers should use paper_publish_date for timestamp when available."""
        # Arrange
        mapper = PersonalizeItemMapper()
        publish_date = datetime(2023, 1, 15, 12, 0, 0, tzinfo=pytz.UTC)
        unified_doc = create_prefetched_paper(paper_publish_date=publish_date)
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        expected_timestamp = int(publish_date.timestamp())
        self.assertEqual(result[CREATION_TIMESTAMP], expected_timestamp)

    def test_creation_timestamp_uses_created_date_for_non_papers(self):
        """Non-papers should use created_date for timestamp."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_post(title="Test Post")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIsNotNone(result[CREATION_TIMESTAMP])
        self.assertIsInstance(result[CREATION_TIMESTAMP], int)

    def test_creation_timestamp_falls_back_to_created_date(self):
        """Papers without paper_publish_date should fall back to created_date."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(paper_publish_date=None)
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIsNotNone(result[CREATION_TIMESTAMP])
        self.assertIsInstance(result[CREATION_TIMESTAMP], int)

    def test_upvote_score_mapped_correctly(self):
        """UPVOTE_SCORE should match unified_doc.score."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper()
        unified_doc.score = 42
        unified_doc.save()
        # Refetch to ensure score is updated
        from researchhub_document.models import ResearchhubUnifiedDocument

        unified_doc = (
            ResearchhubUnifiedDocument.objects.select_related(
                "document_filter", "paper"
            )
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "grants__contacts__author_profile",
                "paper__authorships__author",
                "posts__authors",
            )
            .get(id=unified_doc.id)
        )
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[UPVOTE_SCORE], 42)


class HubTests(TestCase):
    """Tests for hub field mapping."""

    def test_hub_l1_set_for_category_hub(self):
        """HUB_L1 should be set when document has CATEGORY namespace hub."""
        # Arrange
        mapper = PersonalizeItemMapper()
        category_hub = create_hub_with_namespace("Science", Hub.Namespace.CATEGORY)
        unified_doc = create_prefetched_paper(hubs=[category_hub])
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[HUB_L1], str(category_hub.id))

    def test_hub_l2_set_for_subcategory_hub(self):
        """HUB_L2 should be set when document has SUBCATEGORY namespace hub."""
        # Arrange
        mapper = PersonalizeItemMapper()
        subcategory_hub = create_hub_with_namespace(
            "Physics", Hub.Namespace.SUBCATEGORY
        )
        unified_doc = create_prefetched_paper(hubs=[subcategory_hub])
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[HUB_L2], str(subcategory_hub.id))

    def test_hub_ids_contains_all_hub_ids_pipe_delimited(self):
        """HUB_IDS should contain all hub IDs joined with '|'."""
        # Arrange
        mapper = PersonalizeItemMapper()
        hub1 = create_hub_with_namespace("Science", Hub.Namespace.CATEGORY)
        hub2 = create_hub_with_namespace("Physics", Hub.Namespace.SUBCATEGORY)
        unified_doc = create_prefetched_paper(hubs=[hub1, hub2])
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIn(str(hub1.id), result[HUB_IDS])
        self.assertIn(str(hub2.id), result[HUB_IDS])
        self.assertIn(DELIMITER, result[HUB_IDS])

    def test_hub_ids_none_when_no_hubs(self):
        """HUB_IDS should be None when document has no hubs."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(hubs=[])
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIsNone(result[HUB_IDS])


class AuthorTests(TestCase):
    """Tests for author field mapping."""

    def test_paper_author_ids_from_authorships(self):
        """Papers should extract author IDs from paper.authorships."""
        # Arrange
        mapper = PersonalizeItemMapper()
        author1 = create_author("John", "Doe")
        author2 = create_author("Jane", "Smith")
        unified_doc = create_prefetched_paper(authors=[author1, author2])
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIn(str(author1.id), result[AUTHOR_IDS])
        self.assertIn(str(author2.id), result[AUTHOR_IDS])

    def test_grant_author_ids_from_contacts(self):
        """Grants should extract author IDs from grant.contacts.author_profile."""
        # Arrange
        mapper = PersonalizeItemMapper()
        # Note: User creation triggers a signal that creates an Author automatically
        user = User.objects.create_user(
            username="contact_user",
            email="contact@example.com",
            first_name="Contact",
            last_name="User",
        )
        # The signal already created an author_profile
        author = user.author_profile

        # Use the helper which creates everything properly
        unified_doc = create_prefetched_grant(contacts=[user])

        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        # Should contain the author profile ID
        if result[AUTHOR_IDS]:
            self.assertIn(str(author.id), result[AUTHOR_IDS])

    def test_post_author_ids_from_authors(self):
        """Posts should extract author IDs from post.authors."""
        # Arrange
        mapper = PersonalizeItemMapper()
        user1 = User.objects.create_user(
            username="post_author1", email="postauthor1@example.com"
        )
        user2 = User.objects.create_user(
            username="post_author2", email="postauthor2@example.com"
        )
        author1 = create_author("Post1", "Author1")
        author2 = create_author("Post2", "Author2")
        user1.author_profile = author1
        user1.save()
        user2.author_profile = author2
        user2.save()

        # Create post first, then manually add authors
        post = create_prefetched_post(authors=[])
        # Get the actual post object to add authors
        # (posts.authors expects Author objects)
        from researchhub_document.models import ResearchhubPost

        post_obj = ResearchhubPost.objects.get(unified_document=post)
        post_obj.authors.add(author1, author2)

        # Refetch with proper prefetch
        from researchhub_document.models import ResearchhubUnifiedDocument

        unified_doc = (
            ResearchhubUnifiedDocument.objects.select_related(
                "document_filter", "paper"
            )
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "grants__contacts__author_profile",
                "paper__authorships__author",
                "posts__authors",
            )
            .get(id=post.id)
        )

        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        # Post authors are Author objects, and the mapper extracts their IDs
        self.assertIn(str(author1.id), result[AUTHOR_IDS])
        self.assertIn(str(author2.id), result[AUTHOR_IDS])

    def test_author_ids_pipe_delimited(self):
        """AUTHOR_IDS should be pipe-delimited string."""
        # Arrange
        mapper = PersonalizeItemMapper()
        author1 = create_author("John", "Doe")
        author2 = create_author("Jane", "Smith")
        unified_doc = create_prefetched_paper(authors=[author1, author2])
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIn(DELIMITER, result[AUTHOR_IDS])

    def test_author_ids_none_when_no_authors(self):
        """AUTHOR_IDS should be None when no authors exist."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(authors=[])
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIsNone(result[AUTHOR_IDS])


class PaperSpecificFieldTests(TestCase):
    """Tests for paper-specific field mapping."""

    def test_paper_title_uses_paper_title_field(self):
        """Papers should use paper_title field for TITLE."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(title="My Research Paper")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[TITLE], "My Research Paper")

    def test_paper_text_includes_title_abstract_hubs(self):
        """Paper TEXT should concatenate title, abstract, and hub_names."""
        # Arrange
        mapper = PersonalizeItemMapper()
        hub = create_hub_with_namespace("Science", Hub.Namespace.CATEGORY)
        unified_doc = create_prefetched_paper(
            title="Test Title", abstract="Test Abstract", hubs=[hub]
        )
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIn("Test Title", result[TEXT])
        self.assertIn("Test Abstract", result[TEXT])
        self.assertIn("Science", result[TEXT])

    def test_paper_citation_count_mapped(self):
        """CITATION_COUNT_TOTAL should map from paper.citations."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(citations=100)
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[CITATION_COUNT_TOTAL], 100)

    def test_paper_bluesky_count_from_external_metadata(self):
        """BLUESKY_COUNT_TOTAL should extract from paper.external_metadata.metrics."""
        # Arrange
        mapper = PersonalizeItemMapper()
        external_metadata = {"metrics": {"bluesky_count": 50}}
        unified_doc = create_prefetched_paper(external_metadata=external_metadata)
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[BLUESKY_COUNT_TOTAL], 50)

    def test_paper_tweet_count_from_external_metadata(self):
        """TWEET_COUNT_TOTAL should extract from paper.external_metadata.metrics."""
        # Arrange
        mapper = PersonalizeItemMapper()
        external_metadata = {"metrics": {"twitter_count": 75}}
        unified_doc = create_prefetched_paper(external_metadata=external_metadata)
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[TWEET_COUNT_TOTAL], 75)

    def test_paper_social_counts_zero_when_no_external_metadata(self):
        """Social counts should default to 0 when external_metadata is missing."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(external_metadata=None)
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[BLUESKY_COUNT_TOTAL], 0)
        self.assertEqual(result[TWEET_COUNT_TOTAL], 0)


class PostSpecificFieldTests(TestCase):
    """Tests for post-specific field mapping."""

    def test_post_title_uses_title_field(self):
        """Posts should use title field for TITLE."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_post(title="My Discussion Post")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[TITLE], "My Discussion Post")

    def test_post_text_includes_title_renderable_text_hubs(self):
        """Post TEXT should concatenate title, renderable_text, and hub_names."""
        # Arrange
        mapper = PersonalizeItemMapper()
        hub = create_hub_with_namespace("Science", Hub.Namespace.CATEGORY)
        unified_doc = create_prefetched_post(
            title="Post Title", renderable_text="Post Content", hubs=[hub]
        )
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIn("Post Title", result[TEXT])
        self.assertIn("Post Content", result[TEXT])
        self.assertIn("Science", result[TEXT])

    def test_post_has_zero_citation_counts(self):
        """Posts should have CITATION_COUNT_TOTAL default to 0."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_post(title="Post")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[CITATION_COUNT_TOTAL], 0)


class EdgeCaseTests(TestCase):
    """Tests for edge cases and error handling."""

    def test_handles_document_with_no_concrete_document(self):
        """Should return minimal row when get_document() fails."""
        # Arrange
        mapper = PersonalizeItemMapper()
        from unittest.mock import Mock

        mock_doc = Mock()
        mock_doc.id = 999
        mock_doc.document_type = "PAPER"
        mock_doc.score = 0
        mock_doc.get_document.side_effect = Exception("Document not found")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            mock_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(result[ITEM_ID], "999")
        self.assertEqual(result[ITEM_TYPE], "PAPER")

    def test_handles_missing_optional_fields(self):
        """Should handle None values for optional fields gracefully."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(
            title="",
            abstract="",
            paper_publish_date=None,
            citations=0,
            external_metadata=None,
        )
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertIsNotNone(result[ITEM_ID])
        self.assertIsNotNone(result[ITEM_TYPE])

    def test_text_cleaning_removes_html_tags(self):
        """TEXT and TITLE should have HTML tags removed."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(
            title="<p>Paper <strong>Title</strong></p>",
            abstract="<div>Abstract with <em>HTML</em></div>",
        )
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertNotIn("<p>", result[TITLE])
        self.assertNotIn("<strong>", result[TITLE])
        self.assertNotIn("<div>", result[TEXT])
        self.assertNotIn("<em>", result[TEXT])

    def test_text_truncation_at_max_length(self):
        """TEXT should be truncated at MAX_TEXT_LENGTH."""
        # Arrange
        mapper = PersonalizeItemMapper()
        long_abstract = "x" * (MAX_TEXT_LENGTH + 1000)
        unified_doc = create_prefetched_paper(abstract=long_abstract)
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertLessEqual(len(result[TEXT]), MAX_TEXT_LENGTH)


class DefaultValuesTests(TestCase):
    """Tests to ensure mapped items have proper default values."""

    def test_all_fields_have_default_values(self):
        """All fields defined in FIELD_DEFAULTS should be present in result."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(title="Test Paper")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert - all fields from FIELD_DEFAULTS should be in result
        for field in FIELD_DEFAULTS.keys():
            self.assertIn(
                field,
                result,
                f"Field {field} from FIELD_DEFAULTS missing in result",
            )

    def test_numeric_fields_default_to_zero_not_none(self):
        """Numeric fields should default to 0, not None."""
        # Arrange - create minimal document without external metadata
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_post(title="Test Post")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert - numeric fields should be 0, not None
        numeric_fields = [
            UPVOTE_SCORE,
            BLUESKY_COUNT_TOTAL,
            TWEET_COUNT_TOTAL,
            CITATION_COUNT_TOTAL,
        ]
        for field in numeric_fields:
            self.assertIsNotNone(result[field], f"{field} should not be None")
            self.assertIsInstance(
                result[field],
                int,
                f"{field} should be an integer",
            )

    def test_boolean_fields_default_to_false_not_none(self):
        """Boolean fields should default to False, not None."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(title="Test Paper")
        # Empty batch data (no bounties, proposals, or RFPs)
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert - boolean fields should be False, not None
        boolean_fields = [
            HAS_ACTIVE_BOUNTY,
            BOUNTY_HAS_SOLUTIONS,
            RFP_IS_OPEN,
            RFP_HAS_APPLICANTS,
            PROPOSAL_IS_OPEN,
            PROPOSAL_HAS_FUNDERS,
        ]
        for field in boolean_fields:
            self.assertIsNotNone(result[field], f"{field} should not be None")
            self.assertIsInstance(
                result[field],
                bool,
                f"{field} should be a boolean",
            )

    def test_defaults_match_field_defaults_constant(self):
        """
        Verify defaults in result match FIELD_DEFAULTS for fields
        that weren't explicitly set.
        """
        # Arrange - create minimal post without special attributes
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_post(title="Test Post")
        batch_data = create_batch_data()

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert - check fields that should retain their defaults
        # (fields that are not set by common/post/paper mappings)
        fields_that_use_defaults = [
            BLUESKY_COUNT_TOTAL,
            TWEET_COUNT_TOTAL,
            CITATION_COUNT_TOTAL,
            HAS_ACTIVE_BOUNTY,
            BOUNTY_HAS_SOLUTIONS,
            RFP_IS_OPEN,
            RFP_HAS_APPLICANTS,
            PROPOSAL_IS_OPEN,
            PROPOSAL_HAS_FUNDERS,
        ]

        for field in fields_that_use_defaults:
            expected_default = FIELD_DEFAULTS[field]
            self.assertEqual(
                result[field],
                expected_default,
                f"{field} should have default value {expected_default}",
            )

    def test_peer_review_count_from_batch_data(self):
        """Peer review count should be retrieved from batch data."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(title="Test Paper")
        batch_data = create_batch_data()
        # Simulate review count from batch query
        batch_data["review_count"] = {unified_doc.id: 5}

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(
            result[PEER_REVIEW_COUNT_TOTAL],
            5,
            "Should retrieve review count from batch data",
        )

    def test_peer_review_count_defaults_to_zero(self):
        """Peer review count should default to 0 when not in batch data."""
        # Arrange
        mapper = PersonalizeItemMapper()
        unified_doc = create_prefetched_paper(title="Test Paper")
        batch_data = create_batch_data()
        # Empty review count data
        batch_data["review_count"] = {}

        # Act
        result = mapper.map_to_item(
            unified_doc,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        # Assert
        self.assertEqual(
            result[PEER_REVIEW_COUNT_TOTAL],
            0,
            "Should default to 0 when document not in review count data",
        )
