import json
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from note.models import Note
from note.tests.helpers import create_note
from purchase.models import Fundraise, Grant
from reputation.models import Escrow
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.models import User
from user.tests.helpers import create_organization, create_random_default_user


class CreateRegisteredReportTests(APITestCase):
    create_url = "/api/researchhubpost/"

    def setUp(self) -> None:
        """Create users and proposal context for registered report tests."""
        self.user = create_random_default_user("rr_owner")
        self.moderator = create_random_default_user("rr_moderator", moderator=True)
        self.hub = create_hub("registered report hub")
        self.organization = create_organization(
            name="Registered Report Org",
            slug="registered-report-org",
        )
        self.service = JourneyService()
        self.client.force_authenticate(self.user)

    def test_create_report_attaches_proposal(self) -> None:
        """Verify a completed proposal owner can create a registered report."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note = self._create_registered_report_note()
        payload = self._build_payload(proposal, note_id=note.id)

        # Act
        response = self.client.post(self.create_url, payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 200)
        report = ResearchhubPost.objects.get(id=response.data["id"])
        proposal.refresh_from_db()
        self.assertEqual(report.document_type, REGISTERED_REPORT)
        self.assertEqual(report.created_by, self.user)
        self.assertEqual(report.note_id, note.id)
        self.assertEqual(report.journey, proposal.journey)
        self.assertEqual(self.service.get_registered_report(proposal.journey), report)
        self.assertEqual(
            report.unified_document.status,
            ResearchhubUnifiedDocument.APPROVED,
        )
        self.assertTrue(report.unified_document.is_public)
        self.assertCountEqual(report.authors.all(), proposal.authors.all())
        self.assertCountEqual(
            report.unified_document.hubs.all(),
            proposal.unified_document.hubs.all(),
        )
        self.assertEqual(report.image, proposal.image)
        self.assertEqual(report.preview_img, proposal.preview_img)

    def test_create_report_uses_edited_metadata(self) -> None:
        """Verify publishing uses edited registered report authors and image."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note = self._create_registered_report_note()
        payload = self._build_payload(
            proposal,
            authors=[self.user.author_profile.id, self.moderator.author_profile.id],
            note_id=note.id,
            preview_img="https://example.com/edited-preview.png",
        )

        # Act
        response = self.client.post(self.create_url, payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 200)
        report = ResearchhubPost.objects.get(id=response.data["id"])
        self.assertCountEqual(
            report.authors.all(),
            [self.user.author_profile, self.moderator.author_profile],
        )
        self.assertEqual(report.preview_img, "https://example.com/edited-preview.png")

    def test_create_report_persists_published_note_json(self) -> None:
        """Verify publishing stores the editor JSON used by the work page."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note = self._create_registered_report_note()
        full_json = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Published heading"}],
                }
            ],
        }
        payload = self._build_payload(
            proposal,
            full_json=json.dumps(full_json),
            note_id=note.id,
            renderable_text=(
                "Published heading. Registered report body text with enough "
                "content for validation."
            ),
        )

        # Act
        response = self.client.post(self.create_url, payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 200)
        report = ResearchhubPost.objects.get(id=response.data["id"])
        report.note.refresh_from_db()
        self.assertEqual(
            report.note.latest_version.plain_text,
            payload["renderable_text"],
        )
        self.assertEqual(report.note.latest_version.json, full_json)

        work_response = self.client.get(
            f"/api/researchhubpost/{report.id}/registered_report_work/"
        )
        self.assertEqual(work_response.status_code, status.HTTP_200_OK)
        self.assertEqual(work_response.data["work"]["full_json"], full_json)

    def test_reject_generic_note(self) -> None:
        """Verify reports must publish from registered report notes."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note, _ = create_note(self.user, self.organization)
        payload = self._build_payload(proposal, note_id=note.id)

        # Act
        response = self.client.post(self.create_url, payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )

    def test_reject_moderator_for_other_owner(self) -> None:
        """Verify moderators cannot create reports for another user's proposal."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )

    def test_reject_open_proposal(self) -> None:
        """Verify proposals without completed fundraises cannot create reports."""
        # Arrange
        proposal = self._create_open_proposal(self.user)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )

    def test_reject_reported_proposal(self) -> None:
        """Verify proposals with registered reports cannot create another one."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Existing registered report",
        )
        self.service.attach_stage(proposal.journey, report)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).count(),
            1,
        )

    def test_require_login(self) -> None:
        """Verify anonymous users cannot create registered reports."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        self.client.force_authenticate(None)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal),
            format="json",
        )

        # Assert
        self.assertIn(response.status_code, (401, 403))

    def test_retrieve_report_work_returns_tracker_links(self) -> None:
        """Verify registered report work data includes tracker fetch URLs."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        grant_post = self._create_grant_post()
        proposal.journey.grant_post = grant_post
        proposal.journey.save(update_fields=["grant_post"])
        report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Registered report endpoint title",
            renderable_text="Registered report endpoint body.",
        )
        note = self._create_registered_report_note()
        note.refresh_from_db()
        full_json = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Formatted heading"}],
                }
            ],
        }
        note.latest_version.json = full_json
        note.latest_version.save(update_fields=["json"])
        report.note = note
        report.save(update_fields=["note"])
        report.authors.add(self.user.author_profile)
        self.service.attach_stage(proposal.journey, report)

        # Act
        response = self.client.get(
            f"/api/researchhubpost/{report.id}/registered_report_work/"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], report.id)
        self.assertEqual(response.data["content_type"], "RESEARCHHUBPOST")
        self.assertEqual(response.data["content_object"]["id"], report.id)
        self.assertEqual(response.data["work"]["id"], report.id)
        self.assertEqual(
            response.data["work"]["renderable_text"],
            report.renderable_text,
        )
        self.assertNotIn("bounties", response.data["content_object"])
        self.assertNotIn("reviews", response.data["content_object"])
        self.assertNotIn("replies", response.data["metrics"])
        self.assertNotIn("peer_reviews", response.data["work"])
        self.assertNotIn("discussion_count", response.data["work"])
        self.assertIn("formatted_html", response.data["work"])
        self.assertEqual(response.data["work"]["full_json"], full_json)
        self.assertIn("full_src", response.data["work"])
        self.assertEqual(
            response.data["links"],
            {
                "grant": f"http://testserver/api/researchhubpost/{grant_post.id}/",
                "proposal": f"http://testserver/api/researchhubpost/{proposal.id}/",
                "registered_report": (
                    f"http://testserver/api/researchhubpost/{report.id}/"
                ),
            },
        )
        tracker = {step["stage"]: step for step in response.data["tracker"]}
        self.assertTrue(tracker["grant"]["exists"])
        self.assertFalse(tracker["grant"]["is_current"])
        self.assertTrue(tracker["proposal"]["exists"])
        self.assertTrue(tracker["registered_report"]["exists"])
        self.assertTrue(tracker["registered_report"]["is_current"])

    def test_reject_report_work_for_non_report(self) -> None:
        """Verify registered report work data requires a registered report."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)

        # Act
        response = self.client.get(
            f"/api/researchhubpost/{proposal.id}/registered_report_work/"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def _build_payload(
        self, proposal: ResearchhubPost, **overrides: object
    ) -> dict[str, object]:
        """Build a valid registered report request payload."""
        payload = {
            "document_type": REGISTERED_REPORT,
            "proposal_id": proposal.id,
            "title": "Registered report title",
            "renderable_text": (
                "Registered report body. Registered report body. "
                "Registered report body."
            ),
            "full_src": "# Registered report",
        }
        payload.update(overrides)
        return payload

    def _create_registered_report_note(self) -> Note:
        """Create a registered report note draft."""
        note, _ = create_note(self.user, self.organization)
        note.document_type = REGISTERED_REPORT
        note.save(update_fields=["document_type"])
        return note

    def _create_completed_proposal(self, user: User) -> ResearchhubPost:
        """Create an approved proposal with a completed fundraise."""
        proposal = self._create_proposal(user)
        fundraise = Fundraise.objects.create(
            created_by=user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )
        fundraise.escrow = Escrow.objects.create(
            created_by=user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=Decimal(100),
        )
        fundraise.save(update_fields=["escrow"])
        self.service.include_completed_fundraise_in_journal(fundraise)
        proposal.refresh_from_db()
        return proposal

    def _create_open_proposal(self, user: User) -> ResearchhubPost:
        """Create an approved proposal with an open fundraise."""
        proposal = self._create_proposal(user)
        Fundraise.objects.create(
            created_by=user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )
        self.service.ensure_approved_preregistration_has_journey(proposal)
        proposal.refresh_from_db()
        return proposal

    def _create_grant_post(self) -> ResearchhubPost:
        """Create a grant post for tracker links."""
        grant_post = create_post(
            created_by=self.user,
            document_type=GRANT,
            title="Registered report grant",
        )
        Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Registered Report Grant",
            description="Funds registered report work.",
        )
        return grant_post

    def _create_proposal(self, user: User) -> ResearchhubPost:
        """Create an approved preregistration with copied report context."""
        proposal = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            title=f"{user.id} proposal title",
        )
        proposal.authors.add(user.author_profile)
        proposal.unified_document.hubs.add(self.hub)
        proposal.image = "proposal-cover-image-key"
        proposal.preview_img = "https://example.com/proposal-preview.png"
        proposal.save(update_fields=["image", "preview_img"])
        return proposal
