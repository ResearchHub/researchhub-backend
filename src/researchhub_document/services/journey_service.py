from dataclasses import dataclass

from django.db import IntegrityError, transaction

from purchase.models import GrantApplication
from researchhub_document.models import ResearchJourney, ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import (
    JOURNAL_STAGE_GRANT,
    JOURNAL_STAGE_ORDER,
    JOURNAL_STAGE_PROPOSAL,
    JOURNAL_STAGE_REGISTERED_REPORT,
)


@dataclass(frozen=True)
class JourneyStage:
    stage: str
    item: object


class JourneyService:
    def __init__(
        self,
        journey_model=None,
        post_model=None,
        grant_application_model=None,
    ):
        self.journey_model = journey_model or ResearchJourney
        self.post_model = post_model or ResearchhubPost
        self.grant_application_model = grant_application_model or GrantApplication

    @transaction.atomic
    def get_or_create_for_preregistration(self, post):
        self._require_saved_post(post)
        if post.document_type != PREREGISTRATION:
            raise ValueError("Research journeys start from a preregistration post.")

        grant = self._grant_for_preregistration(post)
        journey, _ = self.journey_model.objects.get_or_create(
            preregistration_post=post,
            defaults={
                "created_by": post.created_by,
                "grant": grant,
            },
        )

        update_fields = []
        if journey.created_by_id is None and post.created_by_id is not None:
            journey.created_by = post.created_by
            update_fields.append("created_by")
        if journey.grant_id is None and grant is not None:
            journey.grant = grant
            update_fields.append("grant")
        if update_fields:
            journey.save(update_fields=update_fields)

        self.attach_stage(journey, post)
        return journey

    @transaction.atomic
    def attach_stage(self, journey, post):
        self._require_saved_journey(journey)
        self._require_saved_post(post)

        if post.document_type not in (PREREGISTRATION, REGISTERED_REPORT):
            raise ValueError("Only proposal and registered report posts join journeys.")
        if post.journey_id is not None and post.journey_id != journey.id:
            raise ValueError("Post already belongs to another journey.")

        if post.document_type == PREREGISTRATION:
            self._ensure_proposal_slot(journey, post)
        else:
            if self.proposal(journey) is None:
                raise ValueError("Journey needs a proposal before a registered report.")
            self._ensure_registered_report_slot(journey, post)

        if post.journey_id != journey.id:
            post.journey = journey
            self._save_stage_link(post)

        return post

    def proposal(self, journey):
        self._require_saved_journey(journey)
        if journey.preregistration_post_id is not None:
            return journey.preregistration_post
        return (
            self.post_model.objects.filter(
                journey=journey,
                document_type=PREREGISTRATION,
            )
            .order_by("id")
            .first()
        )

    def registered_report(self, journey):
        self._require_saved_journey(journey)
        return (
            self.post_model.objects.filter(
                journey=journey,
                document_type=REGISTERED_REPORT,
            )
            .order_by("id")
            .first()
        )

    def latest_stage_post(self, journey):
        return self.registered_report(journey) or self.proposal(journey)

    def stages(self, journey):
        self._require_saved_journey(journey)
        stages = []

        if journey.grant_id is not None:
            stages.append(JourneyStage(JOURNAL_STAGE_GRANT, journey.grant))

        proposal = self.proposal(journey)
        if proposal is not None:
            stages.append(JourneyStage(JOURNAL_STAGE_PROPOSAL, proposal))

        registered_report = self.registered_report(journey)
        if registered_report is not None:
            stages.append(
                JourneyStage(JOURNAL_STAGE_REGISTERED_REPORT, registered_report)
            )

        return sorted(stages, key=lambda stage: JOURNAL_STAGE_ORDER[stage.stage])

    def has_registered_report(self, journey):
        return self.registered_report(journey) is not None

    def _grant_for_preregistration(self, post):
        application = (
            self.grant_application_model.objects.filter(preregistration_post=post)
            .select_related("grant")
            .order_by("created_date", "id")
            .first()
        )
        if application is None:
            return None
        return application.grant

    def _ensure_proposal_slot(self, journey, post):
        if (
            journey.preregistration_post_id is not None
            and journey.preregistration_post_id != post.id
        ):
            raise ValueError("Journey already has a proposal.")

        linked_proposal = (
            self.post_model.objects.filter(
                journey=journey,
                document_type=PREREGISTRATION,
            )
            .exclude(id=post.id)
            .order_by("id")
            .first()
        )
        if linked_proposal is not None:
            raise ValueError("Journey already has a proposal.")

        if journey.preregistration_post_id is None:
            journey.preregistration_post = post
            journey.save(update_fields=["preregistration_post"])

    def _ensure_registered_report_slot(self, journey, post):
        registered_report = self.registered_report(journey)
        if registered_report is not None and registered_report.id != post.id:
            raise ValueError("Journey already has a registered report.")

    def _require_saved_post(self, post):
        if post is None or post.pk is None:
            raise ValueError("Post must be saved.")

    def _require_saved_journey(self, journey):
        if journey is None or journey.pk is None:
            raise ValueError("Journey must be saved.")

    def _save_stage_link(self, post):
        try:
            with transaction.atomic():
                post.save(update_fields=["journey"])
        except IntegrityError as error:
            if post.document_type == REGISTERED_REPORT:
                raise ValueError("Journey already has a registered report.") from error
            raise
