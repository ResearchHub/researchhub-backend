from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from purchase.related_models.constants.currency import USD
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.related_models.unified_document_share_link_model import (
    UnifiedDocumentShareLink,
)
from researchhub_document.services.unified_document_share_link_service import (
    SHARE_LINK_TTL,
    UnifiedDocumentShareLinkService,
)
from user.tests.helpers import create_random_default_user


class UnifiedDocumentShareLinkServiceTests(TestCase):
    def setUp(self):
        self.service = UnifiedDocumentShareLinkService()
        self.moderator = create_random_default_user("share-mod", moderator=True)
        self.author = create_random_default_user("share-author")
        self.outsider = create_random_default_user("share-outsider")

        self.proposal = create_post(
            created_by=self.author,
            document_type=PREREGISTRATION,
        )
        self.unified_document = self.proposal.unified_document
        self.unified_document.is_public = False
        self.unified_document.save(update_fields=["is_public"])

    def _expire(self, link):
        UnifiedDocumentShareLink.objects.filter(pk=link.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

    def _create_grant_creator_applying_to_proposal(self):
        grant_creator = create_random_default_user("share-grant-creator")
        grant_post = create_post(created_by=grant_creator, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=grant_creator,
            unified_document=grant_post.unified_document,
            amount=1000,
            currency=USD,
            description="Funding opportunity",
        )
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=self.proposal,
            applicant=self.author,
        )
        return grant_creator

    def test_cannot_create_link_for_proposal_pending_moderation(self):
        # Arrange: a proposal still sitting in the moderation queue
        self.unified_document.status = ResearchhubUnifiedDocument.PENDING
        self.unified_document.save(update_fields=["status"])

        # Act / Assert: eligibility alone is not enough to share it
        with self.assertRaises(ValueError):
            self.service.create_or_get(self.unified_document.id, self.author)
        self.assertFalse(UnifiedDocumentShareLink.objects.exists())

    def test_moderator_can_create_share_link_for_private_proposal(self):
        # Act
        link, created = self.service.create_or_get(
            self.unified_document.id, self.moderator
        )

        # Assert
        self.assertTrue(created)
        self.assertTrue(link.token)
        self.assertEqual(link.created_by, self.moderator)
        self.assertEqual(link.unified_document, self.unified_document)
        self.assertFalse(link.is_expired())
        self.assertAlmostEqual(
            link.expires_at,
            timezone.now() + SHARE_LINK_TTL,
            delta=timedelta(minutes=1),
        )

    def test_creating_link_twice_returns_same_token(self):
        # Arrange
        grant_creator = self._create_grant_creator_applying_to_proposal()
        first, _ = self.service.create_or_get(self.unified_document.id, self.moderator)

        # Act: a different eligible role asks for the link
        second, created = self.service.create_or_get(
            self.unified_document.id, grant_creator
        )

        # Assert: the URL already handed out survives untouched
        self.assertFalse(created)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.token, first.token)
        self.assertEqual(second.expires_at, first.expires_at)
        self.assertEqual(second.created_by, self.moderator)
        self.assertEqual(UnifiedDocumentShareLink.objects.count(), 1)

    def test_creating_link_after_expiry_rotates_token(self):
        # Arrange
        original, _ = self.service.create_or_get(
            self.unified_document.id, self.moderator
        )
        original_token = original.token
        self._expire(original)

        # Act
        rotated, created = self.service.create_or_get(
            self.unified_document.id, self.author
        )

        # Assert
        self.assertTrue(created)
        self.assertEqual(rotated.pk, original.pk)
        self.assertNotEqual(rotated.token, original_token)
        self.assertFalse(rotated.is_expired())
        self.assertEqual(rotated.created_by, self.author)
        self.assertIsNone(self.service.resolve_unified_document_id(original_token))
        self.assertEqual(
            self.service.resolve_unified_document_id(rotated.token),
            self.unified_document.id,
        )

    def test_unaffiliated_user_cannot_create_link(self):
        # Act / Assert
        with self.assertRaises(PermissionError):
            self.service.create_or_get(self.unified_document.id, self.outsider)

        self.assertFalse(UnifiedDocumentShareLink.objects.exists())

    def test_cannot_create_link_for_non_proposal_document(self):
        # Arrange
        discussion = create_post(
            created_by=self.author,
            document_type=DISCUSSION,
        )

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.create_or_get(discussion.unified_document.id, self.moderator)

        self.assertFalse(UnifiedDocumentShareLink.objects.exists())
