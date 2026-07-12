import json
from dataclasses import dataclass
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from note.models import Note, NoteContent
from purchase.models import Fundraise
from researchhub_access_group.constants import ADMIN, NO_ACCESS
from researchhub_access_group.models import Permission
from researchhub_document.models import (
    ResearchhubPost,
    ResearchhubUnifiedDocument,
    ResearchJourney,
)
from researchhub_document.registered_report_note_metadata import (
    add_registered_report_prefill_metadata,
    parse_note_json,
)
from researchhub_document.related_models.constants.document_type import (
    NOTE,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.models import User


@dataclass(frozen=True)
class AcceptedJournalEntry:
    """A journal entry acceptance result."""

    fundraise: Fundraise
    journey: ResearchJourney
    note: Note
    proposal: ResearchhubPost


class JournalEntryService:
    """Service for accepting funded proposals into registered report drafts."""

    def __init__(
        self,
        journey_service: JourneyService | None = None,
    ) -> None:
        """Initialize the service with optional dependencies."""
        self.journey_service = journey_service or JourneyService()

    @transaction.atomic
    def accept_journal_entry(
        self, user: User, user_id: int, fundraise_id: int
    ) -> AcceptedJournalEntry:
        """Create an unpublished registered report note for a completed fundraise."""
        self._validate_user_id(user, user_id)
        fundraise = self._get_fundraise(fundraise_id)
        self._validate_fundraise_owner(fundraise, user)
        self._validate_completed_fundraise(fundraise)
        self._validate_funded_fundraise(fundraise)

        proposal = self._get_fundraise_proposal(fundraise, user)
        journey = self.journey_service.include_completed_fundraise_in_journal(fundraise)
        if journey is None:
            raise ValueError("Fundraise proposal is not eligible for the journal.")
        if self.journey_service.has_registered_report(journey):
            raise ValueError("Fundraise already has a registered report.")

        note = self._create_registered_report_note(user, proposal)
        return AcceptedJournalEntry(
            fundraise=fundraise,
            journey=journey,
            note=note,
            proposal=proposal,
        )

    def get_registered_report_proposal(
        self, user: User, proposal_id: int
    ) -> ResearchhubPost:
        """Return the proposal that can be published as a registered report."""
        proposal = self._get_user_proposal(user, proposal_id)
        fundraise = self._get_completed_fundraise(proposal)
        self._validate_funded_fundraise(fundraise)
        journey = self.journey_service.include_completed_fundraise_in_journal(fundraise)
        if journey is None:
            raise ValueError("Proposal is not eligible for a registered report.")
        if self.journey_service.has_registered_report(journey):
            raise ValueError("Proposal already has a registered report.")
        return proposal

    def get_registered_report_note(self, user: User, note_id: int) -> Note:
        """Return the user's unpublished registered report note."""
        note = Note.objects.filter(
            created_by=user,
            document_type=REGISTERED_REPORT,
            id=note_id,
            unified_document__is_removed=False,
        ).first()
        if note is None:
            raise ValueError("Registered report note not found.")
        if hasattr(note, "post"):
            raise ValueError("Registered report note is already published.")
        return note

    def _validate_user_id(self, user: User, user_id: int) -> None:
        """Validate that the requested user is real and matches the requester."""
        if user.id == user_id:
            return
        if not User.objects.filter(id=user_id).exists():
            raise ValueError("User not found.")
        raise ValueError("Authenticated user cannot accept another user's entry.")

    def _get_fundraise(self, fundraise_id: int) -> Fundraise:
        """Return the requested fundraise or raise a validation error."""
        fundraise = (
            Fundraise.objects.select_related(
                "created_by",
                "escrow",
                "unified_document",
            )
            .filter(id=fundraise_id)
            .first()
        )
        if fundraise is None:
            raise ValueError("Fundraise not found.")
        return fundraise

    def _validate_fundraise_owner(self, fundraise: Fundraise, user: User) -> None:
        """Validate that the fundraise belongs to the requester."""
        if fundraise.created_by_id != user.id:
            raise ValueError("Fundraise does not belong to this user.")

    def _validate_completed_fundraise(self, fundraise: Fundraise) -> None:
        """Validate that the fundraise is completed."""
        if fundraise.status != Fundraise.COMPLETED:
            raise ValueError("Fundraise is not completed.")

    def _validate_funded_fundraise(self, fundraise: Fundraise) -> None:
        """Validate that the completed fundraise has received funding."""
        if self._has_rsc_funding(fundraise) or self._has_usd_funding(fundraise):
            return
        raise ValueError("Fundraise has no completed funding.")

    def _has_rsc_funding(self, fundraise: Fundraise) -> bool:
        """Return whether the fundraise has escrowed or paid RSC funding."""
        if fundraise.escrow is None:
            return False
        funded_amount = fundraise.escrow.amount_holding + fundraise.escrow.amount_paid
        return funded_amount > Decimal(0)

    def _has_usd_funding(self, fundraise: Fundraise) -> bool:
        """Return whether the fundraise has non-refunded USD funding."""
        return fundraise.usd_contributions.filter(
            amount_cents__gt=0,
            is_refunded=False,
        ).exists()

    def _get_fundraise_proposal(
        self, fundraise: Fundraise, user: User
    ) -> ResearchhubPost:
        """Return the proposal owned by the user for the fundraise."""
        proposal = (
            ResearchhubPost.objects.select_related("journey", "unified_document")
            .filter(
                created_by=user,
                document_type=PREREGISTRATION,
                unified_document=fundraise.unified_document,
            )
            .order_by("id")
            .first()
        )
        if proposal is None:
            raise ValueError("Fundraise does not belong to a valid proposal.")
        return proposal

    def _get_user_proposal(self, user: User, proposal_id: int) -> ResearchhubPost:
        """Return the user's approved proposal or raise a validation error."""
        proposal = (
            ResearchhubPost.objects.select_related("journey", "unified_document")
            .filter(
                created_by=user,
                document_type=PREREGISTRATION,
                id=proposal_id,
                unified_document__is_removed=False,
                unified_document__status=ResearchhubUnifiedDocument.APPROVED,
            )
            .first()
        )
        if proposal is None:
            raise ValueError("Proposal is not eligible for a registered report.")
        return proposal

    def _get_completed_fundraise(self, proposal: ResearchhubPost) -> Fundraise:
        """Return the newest completed fundraise for a proposal."""
        fundraise = (
            Fundraise.objects.select_related("escrow", "unified_document")
            .filter(
                status=Fundraise.COMPLETED,
                unified_document=proposal.unified_document,
            )
            .order_by("-created_date", "-id")
            .first()
        )
        if fundraise is None:
            raise ValueError("Proposal is not funded.")
        return fundraise

    def _create_registered_report_note(
        self, user: User, proposal: ResearchhubPost
    ) -> Note:
        """Create a private registered report note from a proposal."""
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=NOTE,
        )
        unified_document.hubs.set(proposal.unified_document.hubs.all())
        note = Note.objects.create(
            created_by=user,
            document_type=REGISTERED_REPORT,
            organization=user.organization,
            title=f"Registered Report: {proposal.title}",
            unified_document=unified_document,
        )
        self._create_private_permissions(user, unified_document)
        NoteContent.objects.create(
            note=note,
            json=self._get_proposal_note_json(proposal),
            plain_text=self._get_proposal_note_plain_text(proposal),
        )
        note.refresh_from_db()
        return note

    def _get_proposal_note_plain_text(self, proposal: ResearchhubPost) -> str:
        """Return the proposal note plain text, falling back to post text."""
        if proposal.note_id is not None and proposal.note.latest_version is not None:
            source_text = proposal.note.latest_version.plain_text
            if source_text is not None:
                return source_text
        return proposal.renderable_text or ""

    def _get_proposal_note_json(self, proposal: ResearchhubPost) -> str:
        """Return proposal notebook JSON with registered report metadata."""
        document = None
        if proposal.note_id is not None and proposal.note.latest_version is not None:
            document = parse_note_json(proposal.note.latest_version.json)
        if document is None:
            document = self._build_note_json(proposal.renderable_text or "")
        document = add_registered_report_prefill_metadata(
            document,
            self._build_registered_report_prefill(proposal),
        )
        return json.dumps(document)

    def _build_registered_report_prefill(
        self, proposal: ResearchhubPost
    ) -> dict[str, object]:
        """Build registered report metadata to persist on a draft note."""
        author_ids = list(proposal.authors.values_list("id", flat=True))
        if not author_ids and proposal.created_by is not None:
            author_ids = [proposal.created_by.author_profile.id]
        return {
            "author_ids": author_ids,
            "image": proposal.image,
            "preview_img": proposal.preview_img,
            "proposal_id": proposal.id,
        }

    def _build_note_json(self, text: str) -> dict[str, object]:
        """Build a ProseMirror document for the current notebook editor."""
        paragraphs = text.splitlines() or [""]
        return {
            "type": "doc",
            "content": [
                self._build_paragraph_json(paragraph) for paragraph in paragraphs
            ],
        }

    def _build_paragraph_json(self, text: str) -> dict[str, object]:
        """Build a ProseMirror paragraph node."""
        paragraph: dict[str, object] = {"type": "paragraph"}
        if text:
            paragraph["content"] = [{"type": "text", "text": text}]
        return paragraph

    def _create_private_permissions(
        self, user: User, unified_document: ResearchhubUnifiedDocument
    ) -> None:
        """Grant the user private admin access to a note document."""
        content_type = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=content_type,
            object_id=unified_document.id,
            user=user,
        )
        Permission.objects.create(
            access_type=NO_ACCESS,
            content_type=content_type,
            object_id=unified_document.id,
            organization=user.organization,
            user=user,
        )
