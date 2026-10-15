from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from purchase.models import Fundraise
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.services.work_cover_service_for_email import (
    build_work_cover,
    format_compact_usd,
)
from user.tests.helpers import create_random_default_user


class BuildWorkCoverTests(TestCase):
    def test_describes_a_proposal_with_its_author_and_fundraise(self) -> None:
        """A proposal's cover credits its author and shows its goal and progress."""
        # Arrange
        creator = create_random_default_user("cover_creator")
        proposal = create_post(created_by=creator, document_type=PREREGISTRATION)
        proposal.reset_post_authors([creator.author_profile.id])
        Fundraise.objects.create(
            created_by=creator,
            unified_document=proposal.unified_document,
            goal_amount=Decimal(10000),
            goal_currency="USD",
        )

        # Act
        cover = build_work_cover(proposal)

        # Assert
        self.assertEqual(
            cover,
            {
                "eyebrow": f"Proposal · {creator.author_profile.full_name}",
                "noun": "a proposal",
                "title": proposal.title,
                "image_url": None,
                "is_discussion": False,
                "raising": "$10K",
                "progress": 0,
            },
        )


class FormatCompactUsdTests(SimpleTestCase):
    def test_keeps_cents_for_sub_dollar_amounts(self) -> None:
        """Small contributions show their cents instead of rounding down to $0."""
        # Arrange
        amounts = [0.3, 0.004]

        # Act
        formatted = [format_compact_usd(amount) for amount in amounts]

        # Assert
        self.assertEqual(formatted, ["$0.30", "<$0.01"])
