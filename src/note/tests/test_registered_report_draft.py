import json
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from note.models import Note, NoteContent
from note.tests.helpers import create_note
from purchase.models import Fundraise
from reputation.models import Escrow
from researchhub_access_group.constants import ADMIN, NO_ACCESS
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost
from researchhub_document.registered_report_note_metadata import (
    REGISTERED_REPORT_PREFILL_ATTR,
)
from researchhub_document.related_models.constants.document_type import (
    NOTE,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.models import User
from user.tests.helpers import create_hub_editor, create_random_default_user


class CreateRegisteredReportDraftTests(APITestCase):
    draft_url = "/api/note/create_registered_report_draft/"

    def setUp(self) -> None:
        """Create proposal owners and authenticate a moderator."""
        self.user = create_random_default_user("journal_entry_owner")
        self.other_user = create_random_default_user("journal_entry_other")
        self.moderator = create_random_default_user(
            "journal_entry_moderator",
            moderator=True,
        )
        self.hub = create_hub("journal entry hub")
        self.journey_service = JourneyService()
        self.client.force_authenticate(self.moderator)

    def test_creates_registered_report_draft_in_moderator_notebook(self) -> None:
        """Verify a moderator creates an unpublished draft for another user."""
        # Arrange
        proposal = self._create_proposal(self.user)
        fundraise = self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))

        # Act
        response = self.client.post(
            self.draft_url,
            self._build_draft_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 201)
        note = Note.objects.get(id=response.data["id"])
        proposal.refresh_from_db()
        self.assertEqual(note.created_by, self.moderator)
        self.assertEqual(note.organization, self.moderator.organization)
        self.assertEqual(note.document_type, REGISTERED_REPORT)
        self.assertEqual(note.unified_document.document_type, NOTE)
        self.assertEqual(note.latest_version.plain_text, proposal.renderable_text)
        self.assertIsInstance(note.latest_version.json, str)
        note_json = json.loads(note.latest_version.json)
        self.assertEqual(note_json["type"], "doc")
        self.assertEqual(
            note_json["content"],
            [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": proposal.renderable_text,
                        }
                    ],
                }
            ],
        )
        self.assertEqual(
            note_json["attrs"][REGISTERED_REPORT_PREFILL_ATTR]["proposal_id"],
            proposal.id,
        )
        self.assertEqual(response.data["access"], "PRIVATE")
        self.assertEqual(response.data["fundraise_id"], fundraise.id)
        self.assertEqual(response.data["journey_id"], proposal.journey_id)
        self.assertEqual(response.data["proposal_id"], proposal.id)
        self.assertIsNone(response.data["post"])
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )
        self.assertCountEqual(
            note.unified_document.hubs.all(),
            proposal.unified_document.hubs.all(),
        )
        self.assertEqual(
            response.data["registered_report_prefill"]["author_ids"],
            [self.user.author_profile.id],
        )
        self.assertEqual(
            response.data["registered_report_prefill"]["hub_ids"],
            [self.hub.id],
        )
        self.assertEqual(
            response.data["registered_report_prefill"]["image"],
            proposal.image,
        )
        self.assertEqual(
            response.data["registered_report_prefill"]["preview_img"],
            proposal.preview_img,
        )
        self.assertEqual(
            response.data["registered_report_prefill"]["proposal_id"],
            proposal.id,
        )
        note_response = self.client.get(f"/api/note/{note.id}/")
        self.assertEqual(note_response.status_code, 200)
        self.assertEqual(
            note_response.data["registered_report_prefill"]["author_ids"],
            [self.user.author_profile.id],
        )
        self.assertEqual(
            note_response.data["registered_report_prefill"]["hub_ids"],
            [self.hub.id],
        )
        self.assertEqual(
            note_response.data["registered_report_prefill"]["image"],
            proposal.image,
        )
        self.assertEqual(
            note_response.data["registered_report_prefill"]["preview_img"],
            proposal.preview_img,
        )
        self.assertEqual(
            note_response.data["registered_report_prefill"]["proposal_id"],
            proposal.id,
        )
        self.assertTrue(proposal.journey.is_in_journal)

    def test_allows_hub_editors_to_create_registered_report_drafts(self) -> None:
        """Verify hub editors can create registered report drafts."""
        # Arrange
        proposal = self._create_proposal(self.user)
        self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))
        editor, _ = create_hub_editor("journal_entry_editor", "Editor Hub")
        self.client.force_authenticate(editor)

        # Act
        response = self.client.post(
            self.draft_url,
            self._build_draft_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 201)
        note = Note.objects.get(id=response.data["id"])
        self.assertEqual(note.created_by, editor)

    def test_preserves_proposal_note_json_in_registered_report_draft(self) -> None:
        """Verify a draft preserves structured proposal notebook content."""
        # Arrange
        proposal = self._create_proposal(self.user)
        source_note, _ = create_note(self.user, self.user.organization)
        formatted_json = json.dumps(
            {
                "type": "doc",
                "content": [
                    {
                        "type": "heading",
                        "attrs": {"level": 2},
                        "content": [{"type": "text", "text": "Abstract"}],
                    },
                    {
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "Preserve formatting.",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        )
        NoteContent.objects.create(
            note=source_note,
            json=formatted_json,
            plain_text="Abstract\nPreserve formatting.",
        )
        source_note.refresh_from_db()
        proposal.note = source_note
        proposal.save(update_fields=["note"])
        self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))

        # Act
        response = self.client.post(
            self.draft_url,
            self._build_draft_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 201)
        note = Note.objects.get(id=response.data["id"])
        note_json = json.loads(note.latest_version.json)
        formatted_data = json.loads(formatted_json)
        self.assertEqual(note_json["type"], formatted_data["type"])
        self.assertEqual(note_json["content"], formatted_data["content"])
        self.assertEqual(
            note_json["attrs"][REGISTERED_REPORT_PREFILL_ATTR]["proposal_id"],
            proposal.id,
        )
        self.assertEqual(
            note.latest_version.plain_text,
            "Abstract\nPreserve formatting.",
        )

    def test_creates_private_permissions_for_moderator_draft(self) -> None:
        """Verify a draft grants private access to its moderator creator."""
        # Arrange
        proposal = self._create_proposal(self.user)
        self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))

        # Act
        response = self.client.post(
            self.draft_url,
            self._build_draft_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 201)
        note = Note.objects.get(id=response.data["id"])
        permissions = note.unified_document.permissions
        self.assertTrue(
            permissions.filter(
                access_type=ADMIN,
                user=self.moderator,
                organization__isnull=True,
            ).exists()
        )
        self.assertTrue(
            permissions.filter(
                access_type=NO_ACCESS,
                user=self.moderator,
                organization=self.moderator.organization,
            ).exists()
        )

    def test_creates_draft_for_another_users_proposal(self) -> None:
        """Verify moderators can create drafts for proposals they do not own."""
        # Arrange
        proposal = self._create_proposal(self.other_user)
        self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))

        # Act
        response = self.client.post(
            self.draft_url,
            self._build_draft_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 201)
        note = Note.objects.get(id=response.data["id"])
        self.assertEqual(note.created_by, self.moderator)
        self.assertEqual(
            response.data["registered_report_prefill"]["proposal_id"],
            proposal.id,
        )

    def test_rejects_open_fundraise(self) -> None:
        """Verify proposals without completed fundraises cannot create drafts."""
        # Arrange
        proposal = self._create_proposal(self.user)
        self._create_fundraise(proposal, Fundraise.OPEN, Decimal(100))

        # Act
        response = self.client.post(
            self.draft_url,
            self._build_draft_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            0,
        )

    def test_rejects_unfunded_fundraise(self) -> None:
        """Verify completed fundraises need funding before draft creation."""
        # Arrange
        proposal = self._create_proposal(self.user)
        self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(0))

        # Act
        response = self.client.post(
            self.draft_url,
            self._build_draft_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            0,
        )

    def test_requires_proposal_id(self) -> None:
        """Verify a moderator must select a proposal to create a draft."""
        # Arrange
        note_count = Note.objects.filter(document_type=REGISTERED_REPORT).count()

        # Act
        response = self.client.post(
            self.draft_url,
            {},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("proposal_id", response.data)
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            note_count,
        )

    def test_rejects_proposal_with_registered_report(self) -> None:
        """Verify proposals with reports cannot create another draft."""
        # Arrange
        proposal = self._create_proposal(self.user)
        fundraise = self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))
        self.journey_service.include_completed_fundraise_in_journal(fundraise)
        proposal.refresh_from_db()
        report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Existing registered report",
        )
        self.journey_service.attach_stage(proposal.journey, report)

        # Act
        response = self.client.post(
            self.draft_url,
            self._build_draft_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            0,
        )

    def test_rejects_regular_users(self) -> None:
        """Verify proposal owners cannot create registered report drafts."""
        # Arrange
        proposal = self._create_proposal(self.user)
        self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(
            self.draft_url,
            self._build_draft_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            0,
        )

    def _build_draft_payload(self, proposal: ResearchhubPost) -> dict[str, int]:
        """Build a registered report draft request for a proposal."""
        return {"proposal_id": proposal.id}

    def _create_proposal(self, user: User) -> ResearchhubPost:
        """Create an approved proposal post with journal context."""
        proposal = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            renderable_text="Proposal content ready for registered report drafting.",
            title=f"{user.username} proposal title",
        )
        proposal.unified_document.hubs.add(self.hub)
        proposal.authors.add(user.author_profile)
        proposal.image = "proposal-cover-image-key"
        proposal.preview_img = "https://example.com/proposal-preview.png"
        proposal.save(update_fields=["image", "preview_img"])
        return proposal

    def _create_fundraise(
        self, proposal: ResearchhubPost, status: str, amount: Decimal
    ) -> Fundraise:
        """Create a fundraise with an escrowed funding amount."""
        fundraise = Fundraise.objects.create(
            created_by=proposal.created_by,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=status,
        )
        fundraise.escrow = Escrow.objects.create(
            created_by=proposal.created_by,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=amount,
        )
        fundraise.save(update_fields=["escrow"])
        return fundraise
