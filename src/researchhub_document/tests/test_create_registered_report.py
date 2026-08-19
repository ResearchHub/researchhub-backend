import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from note.models import Note, NoteContent
from note.tests.helpers import create_note
from paper.related_models.paper_version import PaperVersion
from purchase.models import Fundraise, Grant
from reputation.models import Escrow
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.registered_report_note_metadata import (
    add_registered_report_prefill_metadata,
)
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journal_entry_service import JournalEntryService
from researchhub_document.services.journey_service import JourneyService
from review.models import Review
from user.models import User
from user.tests.helpers import (
    create_hub_editor,
    create_organization,
    create_random_default_user,
)


class CreateRegisteredReportTests(APITestCase):
    create_url = "/api/researchhubpost/"

    def setUp(self) -> None:
        """Create users and authenticate a registered report moderator."""
        self.user = create_random_default_user("rr_owner")
        self.moderator = create_random_default_user("rr_moderator", moderator=True)
        self.hub = create_hub("registered report hub")
        self.organization = create_organization(
            name="Registered Report Org",
            slug="registered-report-org",
        )
        self.service = JourneyService()
        self.doi_patcher = patch(
            "researchhub_document.services.journal_entry_service.DOI"
        )
        self.mock_doi_cls = self.doi_patcher.start()
        self.addCleanup(self.doi_patcher.stop)
        self.mock_doi = MagicMock()
        self.mock_doi.doi = "10.55277/rhj.registered-report.1"
        self.mock_doi.register_doi_for_post.return_value = MagicMock(status_code=200)
        self.mock_doi_cls.return_value = self.mock_doi
        self.client.force_authenticate(self.moderator)

    def test_create_report_attaches_proposal(self) -> None:
        """Verify a moderator can publish a report for an eligible proposal."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        coauthor = create_random_default_user("rr_coauthor")
        proposal_authors = [coauthor.author_profile, self.user.author_profile]
        proposal.reset_post_authors([author.id for author in proposal_authors])
        note = self._create_registered_report_note(proposal)
        payload = self._build_payload(proposal, note_id=note.id)

        # Act
        response = self.client.post(self.create_url, payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 200)
        report = ResearchhubPost.objects.get(id=response.data["id"])
        proposal.refresh_from_db()
        self.assertEqual(report.document_type, REGISTERED_REPORT)
        self.assertEqual(report.created_by, self.moderator)
        self.assertEqual(report.note_id, note.id)
        self.assertEqual(report.journey, proposal.journey)
        self.assertEqual(self.service.get_registered_report(proposal.journey), report)
        self.assertEqual(
            report.unified_document.status,
            ResearchhubUnifiedDocument.APPROVED,
        )
        self.assertTrue(report.unified_document.is_public)
        self.assertEqual(report.ordered_authors, proposal_authors)
        self.assertCountEqual(
            report.unified_document.hubs.all(),
            proposal.unified_document.hubs.all(),
        )
        self.assertEqual(report.image, proposal.image)
        self.assertEqual(report.preview_img, proposal.preview_img)
        self.assertEqual(report.doi, self.mock_doi.doi)
        self.assertEqual(response.data["doi"], self.mock_doi.doi)
        self.mock_doi_cls.assert_called_once_with(
            journal=PaperVersion.RESEARCHHUB,
            version=report.version_number,
        )
        self.mock_doi.register_doi_for_post.assert_called_once_with(
            proposal_authors,
            report.title,
            report,
        )

    def test_rejects_report_when_journal_doi_registration_fails(self) -> None:
        """Verify Crossref failures do not publish a report without its DOI."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note = self._create_registered_report_note(proposal)
        self.mock_doi.register_doi_for_post.return_value = MagicMock(status_code=500)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal, note_id=note.id),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )

    def test_create_report_uses_edited_metadata(self) -> None:
        """Verify publishing uses edited registered report authors and image."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note = self._create_registered_report_note(proposal)
        payload = self._build_payload(
            proposal,
            authors=[self.user.author_profile.id],
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
            [self.user.author_profile],
        )
        self.assertEqual(report.preview_img, "https://example.com/edited-preview.png")

    def test_create_report_persists_published_note_json(self) -> None:
        """Verify publishing stores the editor JSON used by the work page."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note = self._create_registered_report_note(proposal)
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

    def test_published_report_content_cannot_be_changed(self) -> None:
        """Verify publishing freezes both the report and its source note."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        draft = JournalEntryService().create_registered_report_draft(
            self.moderator,
            proposal.id,
        )

        # Act
        publish_response = self.client.post(
            self.create_url,
            self._build_payload(proposal, note_id=draft.note.id),
            format="json",
        )

        # Assert
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)
        report = ResearchhubPost.objects.get(id=publish_response.data["id"])
        note_content_count = NoteContent.objects.filter(note=draft.note).count()

        # Act
        note_response = self.client.post(
            "/api/note_content/",
            {
                "note": draft.note.id,
                "plain_text": "Attempted published content change.",
                "full_json": {"type": "doc", "content": []},
            },
            format="json",
        )
        report_response = self.client.put(
            f"/api/researchhubpost/{report.id}/",
            {"post_id": report.id},
            format="json",
        )

        # Assert
        self.assertEqual(note_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(report_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            note_response.data["detail"],
            "Published registered report content cannot be edited.",
        )
        self.assertEqual(
            report_response.data["detail"],
            "Published registered reports cannot be edited.",
        )
        self.assertEqual(
            NoteContent.objects.filter(note=draft.note).count(),
            note_content_count,
        )

    def test_regular_post_note_content_can_be_changed(self) -> None:
        """Verify only published registered report notes are frozen."""
        # Arrange
        note, _ = create_note(self.user, self.organization)
        post = create_post(created_by=self.user)
        post.note = note
        post.save(update_fields=["note"])
        Permission.objects.create(
            access_type="EDITOR",
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=note.unified_document_id,
            user=self.user,
        )
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(
            "/api/note_content/",
            {
                "note": note.id,
                "plain_text": "Updated regular post content.",
                "full_json": {"type": "doc", "content": []},
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["plain_text"], "Updated regular post content.")

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

    def test_reject_note_for_a_different_proposal(self) -> None:
        """Verify a report draft cannot be published for another proposal."""
        # Arrange
        draft_proposal = self._create_completed_proposal(self.user)
        target_proposal = self._create_completed_proposal(self.user)
        note = self._create_registered_report_note(draft_proposal)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(target_proposal, note_id=note.id),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )

    def test_require_editor_json_when_publishing(self) -> None:
        """Verify every published report has structured work-page content."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note = self._create_registered_report_note(proposal)
        payload = self._build_payload(proposal, note_id=note.id)
        payload.pop("full_json")

        # Act
        response = self.client.post(self.create_url, payload, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )

    def test_hub_editor_can_publish_registered_report(self) -> None:
        """Verify hub editors can publish their registered report drafts."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        editor, _ = create_hub_editor("rr_editor", "Registered Report Editor Hub")
        draft = JournalEntryService().create_registered_report_draft(
            editor,
            proposal.id,
        )
        self.client.force_authenticate(editor)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal, note_id=draft.note.id),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        report = ResearchhubPost.objects.get(id=response.data["id"])
        self.assertEqual(report.created_by, editor)

    def test_reject_regular_user(self) -> None:
        """Verify proposal owners cannot publish registered reports."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note = self._create_registered_report_note(proposal)
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal, note_id=note.id),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )

    def test_reject_open_proposal(self) -> None:
        """Verify proposals without completed fundraises cannot create reports."""
        # Arrange
        proposal = self._create_open_proposal(self.user)
        note = self._create_registered_report_note(proposal)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal, note_id=note.id),
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
        note = self._create_registered_report_note(proposal)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal, note_id=note.id),
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

    def test_retrieves_work_with_tracker_and_reviewer_profile(self) -> None:
        """Verify registered report work data includes tracker and reviewer data."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        grant_post = self._create_grant_post()
        proposal.journey.grant_post = grant_post
        proposal.journey.save(update_fields=["grant_post"])
        proposal.doi = "10.55277/registered-report-proposal"
        proposal.save(update_fields=["doi"])
        reviewer_profile_image = "https://example.com/reviewer-profile.jpg"
        self.moderator.author_profile.profile_image = reviewer_profile_image
        self.moderator.author_profile.save(update_fields=["profile_image"])
        active_review = Review.objects.create(
            created_by=self.moderator,
            unified_document=proposal.unified_document,
            content_type=ContentType.objects.get_for_model(proposal),
            object_id=proposal.id,
            score=8,
            is_assessed=True,
        )
        Review.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            content_type=ContentType.objects.get_for_model(proposal),
            object_id=proposal.id,
            score=3,
            is_removed=True,
        )
        report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Registered report endpoint title",
            renderable_text="Registered report endpoint body.",
        )
        report.doi = "10.55277/registered-report"
        report.save(update_fields=["doi"])
        note = self._create_registered_report_note(proposal)
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
        self.assertEqual(response.data["content_object"]["doi"], report.doi)
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
        self.assertNotIn("url", response.data["content_object"]["proposal"])
        proposal_data = response.data["content_object"]["proposal"]
        self.assertEqual(proposal_data["doi"], proposal.doi)
        self.assertEqual(proposal_data["document_type"], PREREGISTRATION)
        self.assertEqual(proposal_data["status"], proposal.unified_document.status)
        self.assertEqual(proposal_data["hubs"][0]["id"], self.hub.id)
        self.assertEqual(proposal_data["authors"][0]["id"], self.user.author_profile.id)
        self.assertEqual(proposal_data["created_by"]["id"], self.user.id)
        self.assertEqual(len(proposal_data["peer_reviews"]), 1)
        self.assertEqual(proposal_data["peer_reviews"][0]["id"], active_review.id)
        self.assertEqual(
            proposal_data["peer_reviews"][0]["created_by"]["id"],
            self.moderator.id,
        )
        self.assertEqual(
            proposal_data["peer_reviews"][0]["created_by"]["is_verified"],
            self.moderator.is_verified,
        )
        self.assertEqual(
            proposal_data["peer_reviews"][0]["created_by"]["author_profile"][
                "profile_image"
            ],
            reviewer_profile_image,
        )
        self.assertEqual(response.data["work"]["full_json"], full_json)
        self.assertNotIn("formatted_html", response.data["work"])
        self.assertNotIn("full_markdown", response.data["work"])
        self.assertNotIn("full_src", response.data["work"])
        self.assertNotIn("post_src", response.data["work"])
        self.assertNotIn("links", response.data)
        tracker = {step["stage"]: step for step in response.data["tracker"]}
        self.assertTrue(tracker["grant"]["exists"])
        self.assertFalse(tracker["grant"]["is_current"])
        self.assertEqual(tracker["grant"]["post_id"], grant_post.id)
        self.assertEqual(tracker["grant"]["title"], grant_post.title)
        self.assertNotIn("url", tracker["grant"])
        self.assertTrue(tracker["proposal"]["exists"])
        self.assertEqual(tracker["proposal"]["post_id"], proposal.id)
        self.assertEqual(tracker["proposal"]["title"], proposal.title)
        self.assertNotIn("url", tracker["proposal"])
        self.assertTrue(tracker["registered_report"]["exists"])
        self.assertTrue(tracker["registered_report"]["is_current"])
        self.assertEqual(tracker["registered_report"]["post_id"], report.id)
        self.assertEqual(tracker["registered_report"]["title"], report.title)
        self.assertNotIn("url", tracker["registered_report"])

        # Act
        proposal.unified_document.is_public = False
        proposal.unified_document.save(update_fields=["is_public"])
        outsider = create_random_default_user("rr_work_page_outsider")
        self.client.force_authenticate(outsider)

        redacted_response = self.client.get(
            f"/api/researchhubpost/{report.id}/registered_report_work/"
        )

        # Assert
        self.assertEqual(redacted_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(redacted_response.data["content_object"]["proposal"])
        redacted_tracker = {
            step["stage"]: step for step in redacted_response.data["tracker"]
        }
        self.assertFalse(redacted_tracker["proposal"]["exists"])
        self.assertIsNone(redacted_tracker["proposal"]["post_id"])
        self.assertIsNone(redacted_tracker["proposal"]["title"])

    def test_reject_report_work_for_non_report(self) -> None:
        """Verify registered report work data requires a registered report."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)

        # Act
        response = self.client.get(
            f"/api/researchhubpost/{proposal.id}/registered_report_work/"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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
            "full_json": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "Registered report body.",
                            }
                        ],
                    }
                ],
            },
            "full_src": "# Registered report",
        }
        payload.update(overrides)
        return payload

    def _create_registered_report_note(self, proposal: ResearchhubPost) -> Note:
        """Create a registered report note draft for the given proposal."""
        note, _ = create_note(self.moderator, self.moderator.organization)
        note.document_type = REGISTERED_REPORT
        note.save(update_fields=["document_type"])
        note.refresh_from_db()
        note.latest_version.json = add_registered_report_prefill_metadata(
            {"type": "doc", "content": []},
            {"proposal_id": proposal.id},
        )
        note.latest_version.save(update_fields=["json"])
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
        self.service.ensure_approved_preregistration_has_journey(proposal)
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
        """Create a grant post for the tracker."""
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
            status=Grant.COMPLETED,
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
