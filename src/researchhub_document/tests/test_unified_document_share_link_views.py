from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from purchase.related_models.constants.currency import USD
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.related_models.unified_document_share_link_model import (
    UnifiedDocumentShareLink,
)
from researchhub_document.services.unified_document_share_link_service import (
    UnifiedDocumentShareLinkService,
)
from user.tests.helpers import create_hub_editor, create_random_default_user


class UnifiedDocumentShareLinkViewTests(APITestCase):
    def setUp(self):
        self.service = UnifiedDocumentShareLinkService()
        self.moderator = create_random_default_user("view-mod", moderator=True)
        self.author = create_random_default_user("view-author")

        self.proposal = self._create_private_proposal("Gene editing proposal")
        self.unified_document = self.proposal.unified_document
        self.fundraise = Fundraise.objects.create(
            created_by=self.author,
            unified_document=self.unified_document,
            goal_amount=5000,
            goal_currency=USD,
        )
        # Serializing a fundraise converts its goal via the latest exchange rate.
        RscExchangeRate.objects.create(rate=1.0)

    def _create_private_proposal(self, title):
        proposal = create_post(
            title=title,
            created_by=self.author,
            document_type=PREREGISTRATION,
        )
        unified_document = proposal.unified_document
        unified_document.is_public = False
        unified_document.save(update_fields=["is_public"])
        return proposal

    def _create_grant_creator_applying_to_proposal(self):
        grant_creator = create_random_default_user("view-grant-creator")
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

    def _mint(self, proposal):
        link, _ = self.service.create_or_get(
            proposal.unified_document_id, self.moderator
        )
        return link

    def test_anonymous_user_can_view_private_proposal_with_valid_token(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act: mint the link, then load the proposal page as an anonymous visitor
        create_response = self.client.post(
            f"/api/researchhub_unified_document/{self.unified_document.id}/share_link/"
        )
        token = create_response.data["token"]
        self.client.force_authenticate(user=None)
        post_response = self.client.get(
            f"/api/researchhubpost/{self.proposal.id}/?st={token}"
        )
        metadata_response = self.client.get(
            f"/api/researchhub_unified_document/{self.unified_document.id}"
            f"/get_document_metadata/?st={token}"
        )

        # Assert
        self.assertEqual(create_response.status_code, 201)
        self.assertTrue(token)
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(post_response.data["id"], self.proposal.id)
        self.assertEqual(post_response.data["title"], "Gene editing proposal")
        self.assertEqual(metadata_response.status_code, 200)
        self.assertEqual(metadata_response.data["fundraise"]["id"], self.fundraise.id)

    def test_eligible_user_can_fetch_existing_link_without_minting_one(self):
        # Arrange
        link = self._mint(self.proposal)
        url = (
            f"/api/researchhub_unified_document/{self.unified_document.id}/share_link/"
        )

        # Act
        self.client.force_authenticate(self.author)
        response = self.client.get(url)

        # Assert: reads the same token back, and creates nothing
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["token"], link.token)
        self.assertEqual(UnifiedDocumentShareLink.objects.count(), 1)

    def test_fetching_link_is_restricted_to_authors_admins_editors_and_grant_creators(
        self,
    ):
        # Arrange
        link = self._mint(self.proposal)
        url = (
            f"/api/researchhub_unified_document/{self.unified_document.id}/share_link/"
        )
        editor, _ = create_hub_editor("view-hub-editor", "view-share-link-hub")
        grant_creator = self._create_grant_creator_applying_to_proposal()
        outsider = create_random_default_user("view-outsider-get")

        # Act / Assert: each eligible role reads the same link
        for eligible_user in (self.author, self.moderator, editor, grant_creator):
            self.client.force_authenticate(eligible_user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, eligible_user.email)
            self.assertEqual(response.data["token"], link.token)

        # Assert: an unaffiliated authenticated user is refused
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(url).status_code, 403)

        # Assert: an anonymous request is refused before it even reaches the
        # eligibility check, since the action requires authentication
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(url).status_code, 401)

    def test_fetching_link_returns_404_when_absent_or_expired(self):
        # Arrange
        url = (
            f"/api/researchhub_unified_document/{self.unified_document.id}/share_link/"
        )
        self.client.force_authenticate(self.author)

        # Act
        absent_response = self.client.get(url)
        link = self._mint(self.proposal)
        UnifiedDocumentShareLink.objects.filter(pk=link.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )
        expired_response = self.client.get(url)

        # Assert: a lapsed link reads as no link, and fetching does not renew it
        self.assertEqual(absent_response.status_code, 404)
        self.assertEqual(expired_response.status_code, 404)
        self.assertEqual(
            UnifiedDocumentShareLink.objects.get(pk=link.pk).token, link.token
        )

    def test_turning_sharing_off_kills_the_link_and_later_reshare_differs(self):
        # Arrange
        link = self._mint(self.proposal)
        post_url = f"/api/researchhubpost/{self.proposal.id}/"
        self.assertEqual(
            self.client.get(f"{post_url}?st={link.token}").status_code, 200
        )

        # Act
        self.client.force_authenticate(self.moderator)
        disable_response = self.client.delete(
            f"/api/researchhub_unified_document/{self.unified_document.id}/share_link/"
        )
        reshare_response = self.client.post(
            f"/api/researchhub_unified_document/{self.unified_document.id}/share_link/"
        )
        self.client.force_authenticate(user=None)
        revoked_response = self.client.get(f"{post_url}?st={link.token}")

        # Assert: the old URL stays dead even after sharing is turned back on
        self.assertEqual(disable_response.status_code, 204)
        self.assertEqual(revoked_response.status_code, 404)
        self.assertEqual(reshare_response.status_code, 201)
        self.assertNotEqual(reshare_response.data["token"], link.token)

    def test_unaffiliated_user_cannot_turn_sharing_off(self):
        # Arrange
        link = self._mint(self.proposal)
        outsider = create_random_default_user("view-outsider")

        # Act
        self.client.force_authenticate(outsider)
        response = self.client.delete(
            f"/api/researchhub_unified_document/{self.unified_document.id}/share_link/"
        )

        # Assert
        self.assertEqual(response.status_code, 403)
        self.assertTrue(UnifiedDocumentShareLink.objects.filter(pk=link.pk).exists())

    def test_share_link_does_not_expose_proposal_elsewhere(self):
        # Arrange
        self._mint(self.proposal)

        # Act
        post_response = self.client.get(f"/api/researchhubpost/{self.proposal.id}/")
        metadata_response = self.client.get(
            f"/api/researchhub_unified_document/{self.unified_document.id}"
            "/get_document_metadata/"
        )
        fundraise_response = self.client.get(f"/api/fundraise/{self.fundraise.id}/")

        # Assert: the token unlocks one document through one surface only
        self.assertEqual(post_response.status_code, 404)
        self.assertEqual(metadata_response.status_code, 403)
        self.assertEqual(fundraise_response.status_code, 401)
        self.assertFalse(
            ResearchhubPost.objects.visible_to(None)
            .filter(pk=self.proposal.pk)
            .exists()
        )

    def test_share_token_does_not_unlock_a_different_proposal(self):
        # Arrange
        other_proposal = self._create_private_proposal("Unrelated proposal")
        link = self._mint(self.proposal)

        # Act: a valid token paired with someone else's document
        post_response = self.client.get(
            f"/api/researchhubpost/{other_proposal.id}/?st={link.token}"
        )
        metadata_response = self.client.get(
            f"/api/researchhub_unified_document/{other_proposal.unified_document_id}"
            f"/get_document_metadata/?st={link.token}"
        )

        # Assert
        self.assertEqual(post_response.status_code, 404)
        self.assertEqual(metadata_response.status_code, 403)

    def test_share_token_keeps_embedded_document_unredacted(self):
        # Arrange
        link = self._mint(self.proposal)

        # Act
        response = self.client.get(
            f"/api/researchhub_unified_document/{self.unified_document.id}"
            f"/get_document_metadata/?st={link.token}"
        )

        # Assert: the embedded post keeps the fields the page asked for rather
        # than collapsing to the redaction stub
        document = response.data["documents"][0]
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(document, {"id": self.proposal.id, "is_public": False})
        self.assertIn("discussion_aggregates", document)

    def test_share_token_stops_working_once_proposal_leaves_approved(self):
        # Arrange: a link minted while approved, then sent back for moderation
        link = self._mint(self.proposal)
        self.unified_document.status = ResearchhubUnifiedDocument.DECLINED
        self.unified_document.save(update_fields=["status"])

        # Act
        post_response = self.client.get(
            f"/api/researchhubpost/{self.proposal.id}/?st={link.token}"
        )
        metadata_response = self.client.get(
            f"/api/researchhub_unified_document/{self.unified_document.id}"
            f"/get_document_metadata/?st={link.token}"
        )

        # Assert: an already-shared link cannot outlive the decline
        self.assertEqual(post_response.status_code, 404)
        self.assertEqual(metadata_response.status_code, 403)

    def test_expired_or_unknown_share_token_does_not_unlock_the_proposal_page(self):
        # Arrange
        link = self._mint(self.proposal)
        UnifiedDocumentShareLink.objects.filter(pk=link.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )
        post_url = f"/api/researchhubpost/{self.proposal.id}/"
        metadata_url = (
            f"/api/researchhub_unified_document/{self.unified_document.id}"
            "/get_document_metadata/"
        )

        # Act
        expired_post = self.client.get(f"{post_url}?st={link.token}")
        expired_metadata = self.client.get(f"{metadata_url}?st={link.token}")
        unknown_post = self.client.get(f"{post_url}?st=not-a-real-token")

        # Assert: an expired link reads exactly like no link at all
        self.assertEqual(expired_post.status_code, 404)
        self.assertEqual(expired_metadata.status_code, 403)
        self.assertEqual(unknown_post.status_code, 404)
