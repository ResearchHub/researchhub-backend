import json
from collections.abc import Callable
from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Exists, F, OuterRef, QuerySet
from requests.exceptions import RequestException

from note.models import Note, NoteContent
from paper.related_models.paper_version import PaperVersion
from purchase.models import Fundraise
from purchase.services.fundraise_eligibility_service import (
    filter_fundraises_with_funding,
)
from researchhub_access_group.constants import ADMIN, NO_ACCESS
from researchhub_access_group.models import Permission
from researchhub_document.models import (
    ResearchhubPost,
    ResearchhubUnifiedDocument,
    ResearchJourney,
)
from researchhub_document.registered_report_note_metadata import (
    add_registered_report_prefill_metadata,
    get_registered_report_prefill_metadata,
    parse_note_json,
)
from researchhub_document.related_models.constants.document_type import (
    NOTE,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from researchhub_document.services.researchhub_post_author_service import (
    list_authors,
)
from user.models import Author, User
from utils.doi import DOI


@dataclass(frozen=True)
class RegisteredReportDraft:
    """A registered report draft created from an eligible proposal."""

    fundraise: Fundraise
    journey: ResearchJourney
    note: Note
    proposal: ResearchhubPost


class RegisteredReportDraftValidationError(ValueError):
    """Raised when a proposal is ineligible for a registered report draft."""


class RegisteredReportDOIRegistrationError(Exception):
    """Raised when Crossref cannot register a registered report DOI."""


class JournalEntryService:
    """Service for evaluating, drafting, and publishing registered reports."""

    def __init__(
        self,
        journey_service: JourneyService | None = None,
        doi_factory: Callable[..., DOI] | None = None,
    ) -> None:
        """Initialize the service with optional dependencies."""
        self.journey_service = journey_service or JourneyService()
        self._doi_factory = doi_factory or DOI

    @transaction.atomic
    def create_registered_report_draft(
        self, creator: User, proposal_id: int
    ) -> RegisteredReportDraft:
        """Create an editor- or moderator-owned draft from an eligible proposal."""
        proposal, fundraise, journey = self._get_registered_report_context(proposal_id)
        note = self._create_registered_report_note(creator, proposal)
        return RegisteredReportDraft(
            fundraise=fundraise,
            journey=journey,
            note=note,
            proposal=proposal,
        )

    def get_registered_report_proposal(self, proposal_id: int) -> ResearchhubPost:
        """Return the proposal that can be published as a registered report."""
        proposal, _, _ = self._get_registered_report_context(proposal_id)
        return proposal

    def list_registered_report_candidates(self) -> QuerySet:
        """Return funded proposals with valid journeys and no registered report."""
        funded_fundraises = filter_fundraises_with_funding(
            Fundraise.objects.filter(
                unified_document_id=OuterRef("unified_document_id"),
                status=Fundraise.COMPLETED,
            )
        )
        registered_reports = ResearchhubPost.objects.filter(
            document_type=REGISTERED_REPORT,
            journey_id=OuterRef("journey_id"),
        )
        return ResearchhubPost.objects.filter(
            document_type=PREREGISTRATION,
            journey__preregistration_post_id=F("pk"),
            unified_document__is_removed=False,
            unified_document__status=ResearchhubUnifiedDocument.APPROVED,
        ).filter(Exists(funded_fundraises), ~Exists(registered_reports))

    def get_registered_report_authors(self, proposal: ResearchhubPost) -> list[Author]:
        """Return proposal authors or its creator for a registered report."""
        authors = list_authors(proposal)
        if authors:
            return authors
        if proposal.created_by is not None:
            return [proposal.created_by.author_profile]
        return []

    def register_registered_report_doi(
        self,
        report: ResearchhubPost,
        authors: list[Author],
    ) -> None:
        """Register and persist the published report's journal DOI."""
        doi = self._doi_factory(
            journal=PaperVersion.RESEARCHHUB,
            version=report.version_number,
        )
        try:
            response = doi.register_doi_for_post(authors, report.title, report)
        except RequestException as error:
            raise RegisteredReportDOIRegistrationError(
                "Crossref did not respond while registering the registered report DOI."
            ) from error

        if response.status_code != 200:
            raise RegisteredReportDOIRegistrationError(
                "Crossref could not register the registered report DOI."
            )

        report.doi = doi.doi
        report.save(update_fields=["doi"])

    def get_registered_report_note(
        self, creator: User, note_id: int, proposal: ResearchhubPost
    ) -> Note:
        """Return the creator's unpublished draft for the requested proposal."""
        note = Note.objects.filter(
            created_by=creator,
            document_type=REGISTERED_REPORT,
            id=note_id,
            unified_document__is_removed=False,
        ).first()
        if note is None:
            raise ValueError("Registered report note not found.")
        if hasattr(note, "post"):
            raise ValueError("Registered report note is already published.")
        if note.latest_version is None:
            raise ValueError("Registered report note has no content.")

        metadata = get_registered_report_prefill_metadata(note.latest_version.json)
        if metadata.get("proposal_id") != proposal.id:
            raise ValueError("Registered report note does not belong to this proposal.")
        return note

    def persist_registered_report_content(
        self,
        note: Note,
        plain_text: str,
        document: dict[str, object],
        created_by: User | None = None,
    ) -> None:
        """Save the final immutable editor document before publishing its report."""
        NoteContent.objects.create(
            note=note,
            plain_text=plain_text,
            json=document,
            created_by=created_by,
            created_via=NoteContent.CREATED_VIA_SYSTEM,
        )

    def _get_registered_report_context(
        self, proposal_id: int
    ) -> tuple[ResearchhubPost, Fundraise, ResearchJourney]:
        """Return the eligible proposal, fundraise, and journey for a report."""
        proposal = self._get_approved_proposal(proposal_id)
        fundraise = self._get_funded_completed_fundraise(proposal)
        journey = self.journey_service.ensure_approved_preregistration_has_journey(
            proposal
        )
        if journey is None:
            raise RegisteredReportDraftValidationError(
                "Proposal is not eligible for a registered report."
            )
        if self.journey_service.has_registered_report(journey):
            raise RegisteredReportDraftValidationError(
                "Proposal already has a registered report."
            )
        return proposal, fundraise, journey

    def _get_approved_proposal(self, proposal_id: int) -> ResearchhubPost:
        """Return an approved proposal or raise a validation error."""
        proposal = (
            ResearchhubPost.objects.select_related("journey", "unified_document")
            .filter(
                document_type=PREREGISTRATION,
                id=proposal_id,
                unified_document__is_removed=False,
                unified_document__status=ResearchhubUnifiedDocument.APPROVED,
            )
            .first()
        )
        if proposal is None:
            raise RegisteredReportDraftValidationError(
                "Proposal is not eligible for a registered report."
            )
        return proposal

    def _get_funded_completed_fundraise(self, proposal: ResearchhubPost) -> Fundraise:
        """Return the newest completed fundraise with non-refunded funding."""
        fundraise = (
            filter_fundraises_with_funding(
                Fundraise.objects.filter(
                    status=Fundraise.COMPLETED,
                    unified_document=proposal.unified_document,
                )
            )
            .select_related("escrow", "unified_document")
            .order_by("-created_date", "-id")
            .first()
        )
        if fundraise is None:
            raise RegisteredReportDraftValidationError("Proposal is not funded.")
        return fundraise

    def _create_registered_report_note(
        self, creator: User, proposal: ResearchhubPost
    ) -> Note:
        """Create a private editor- or moderator-owned report note from a proposal."""
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=NOTE,
        )
        unified_document.hubs.set(proposal.unified_document.hubs.all())
        note = Note.objects.create(
            created_by=creator,
            document_type=REGISTERED_REPORT,
            organization=creator.organization,
            title=f"Registered Report: {proposal.title}",
            unified_document=unified_document,
        )
        self._create_private_permissions(creator, unified_document)
        NoteContent.objects.create(
            note=note,
            json=self._get_proposal_note_json(proposal),
            plain_text=self._get_proposal_note_plain_text(proposal),
            created_by=creator,
            created_via=NoteContent.CREATED_VIA_SYSTEM,
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
        authors = self.get_registered_report_authors(proposal)
        author_ids = [author.id for author in authors]
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
        self, creator: User, unified_document: ResearchhubUnifiedDocument
    ) -> None:
        """Grant the creator private admin access to a note document."""
        content_type = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=content_type,
            object_id=unified_document.id,
            user=creator,
        )
        Permission.objects.create(
            access_type=NO_ACCESS,
            content_type=content_type,
            object_id=unified_document.id,
            organization=creator.organization,
            user=creator,
        )
