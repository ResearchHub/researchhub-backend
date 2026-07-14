from __future__ import annotations

from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.db.models import Prefetch, QuerySet

from purchase.models import Fundraise, UsdFundraiseContribution
from researchhub_document.models import (
    ResearchhubPost,
    ResearchhubUnifiedDocument,
    ResearchJourney,
)
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.services.journey_service import JourneyService


@dataclass(frozen=True)
class ResearchJourneyBackfillFailure:
    """Describe one proposal that could not be backfilled."""

    proposal_id: int
    message: str


@dataclass
class ResearchJourneyBackfillStats:
    """Track research journey backfill outcomes."""

    proposals_processed: int = 0
    journey_changes: int = 0
    journal_candidates_processed: int = 0
    journal_inclusion_changes: int = 0
    failures: list[ResearchJourneyBackfillFailure] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        """Return whether one or more proposal backfills failed."""
        return bool(self.failures)


class ResearchJourneyBackfillService:
    """Backfill approved proposal journeys and journal inclusion."""

    def __init__(self, journey_service: JourneyService | None = None) -> None:
        """Initialize the service with the journey service dependency."""
        self._journey_service = journey_service or JourneyService()

    def backfill(
        self, *, chunk_size: int, dry_run: bool
    ) -> ResearchJourneyBackfillStats:
        """Create journeys and include eligible proposals in the journal."""
        stats = ResearchJourneyBackfillStats()

        for proposal in self._get_approved_proposals().iterator(chunk_size=chunk_size):
            stats.proposals_processed += 1
            fundraise = self._get_latest_completed_fundraise(proposal)

            if dry_run:
                self._count_dry_run_changes(stats, proposal, fundraise)
                continue

            try:
                self._backfill_proposal(stats, proposal, fundraise)
            except (IntegrityError, ValueError) as error:
                stats.failures.append(
                    ResearchJourneyBackfillFailure(
                        proposal_id=proposal.id,
                        message=str(error),
                    )
                )

        return stats

    def _get_approved_proposals(self) -> QuerySet[ResearchhubPost]:
        """Return approved proposals with their completed funding context."""
        completed_fundraises = (
            Fundraise.objects.filter(status=Fundraise.COMPLETED)
            .select_related("escrow")
            .prefetch_related(
                Prefetch(
                    "usd_contributions",
                    queryset=UsdFundraiseContribution.objects.filter(
                        amount_cents__gt=0,
                        is_refunded=False,
                    ),
                    to_attr="prefetched_eligible_usd_contributions",
                )
            )
            .order_by("-created_date", "-id")
        )

        return (
            ResearchhubPost.objects.filter(
                document_type=PREREGISTRATION,
                unified_document__is_removed=False,
                unified_document__status=ResearchhubUnifiedDocument.APPROVED,
            )
            .select_related("journey", "unified_document")
            .prefetch_related(
                Prefetch(
                    "unified_document__fundraises",
                    queryset=completed_fundraises,
                    to_attr="prefetched_completed_fundraises",
                )
            )
            .order_by("id")
        )

    @transaction.atomic
    def _backfill_proposal(
        self,
        stats: ResearchJourneyBackfillStats,
        proposal: ResearchhubPost,
        fundraise: Fundraise | None,
    ) -> None:
        """Persist journey changes for one approved proposal."""
        had_complete_journey = self._has_complete_journey(proposal)
        journey = self._get_or_create_journey(proposal)
        if not had_complete_journey:
            stats.journey_changes += 1

        if (
            fundraise is None
            or not self._journey_service.is_completed_fundraise_eligible(fundraise)
        ):
            return

        stats.journal_candidates_processed += 1
        had_journal_inclusion = self._has_journal_inclusion(journey)
        self._journey_service.include_journey_in_journal(journey)
        if not had_journal_inclusion:
            stats.journal_inclusion_changes += 1

    def _count_dry_run_changes(
        self,
        stats: ResearchJourneyBackfillStats,
        proposal: ResearchhubPost,
        fundraise: Fundraise | None,
    ) -> None:
        """Count proposal changes without creating or updating journeys."""
        if not self._has_complete_journey(proposal):
            stats.journey_changes += 1
        if (
            fundraise is None
            or not self._journey_service.is_completed_fundraise_eligible(fundraise)
        ):
            return

        stats.journal_candidates_processed += 1
        if not self._has_journal_inclusion(proposal.journey):
            stats.journal_inclusion_changes += 1

    def _get_latest_completed_fundraise(
        self, proposal: ResearchhubPost
    ) -> Fundraise | None:
        """Return the newest completed fundraise prefetched for a proposal."""
        fundraises = getattr(
            proposal.unified_document,
            "prefetched_completed_fundraises",
            [],
        )
        return fundraises[0] if fundraises else None

    def _get_or_create_journey(self, proposal: ResearchhubPost) -> ResearchJourney:
        """Return the proposal journey after ensuring both links are complete."""
        if proposal.journey_id is None:
            return self._journey_service.get_or_create_for_preregistration(proposal)

        self._journey_service.attach_stage(proposal.journey, proposal)
        return proposal.journey

    def _has_complete_journey(self, proposal: ResearchhubPost) -> bool:
        """Return whether a proposal and journey correctly point to each other."""
        journey = proposal.journey
        return journey is not None and journey.preregistration_post_id == proposal.id

    def _has_journal_inclusion(self, journey: ResearchJourney | None) -> bool:
        """Return whether a journey is fully included in the journal."""
        return (
            journey is not None
            and journey.is_in_journal
            and journey.journal_included_date is not None
        )
