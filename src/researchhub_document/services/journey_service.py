from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Prefetch, QuerySet
from django.utils import timezone
from django.utils.text import slugify

from purchase.models import Fundraise, GrantApplication
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.models import (
    ResearchhubPost,
    ResearchhubUnifiedDocument,
    ResearchJourney,
)
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.constants.editor_type import CK_EDITOR
from researchhub_document.related_models.constants.journey_stage import (
    JOURNEY_STAGE_GRANT,
    JOURNEY_STAGE_ORDER,
    JOURNEY_STAGE_PROPOSAL,
    JOURNEY_STAGE_REGISTERED_REPORT,
)
from user.models import User

REGISTERED_REPORT_RESULTS_REFERENCE = "REGISTERED_REPORT_RESULTS"


@dataclass(frozen=True)
class JourneyStage:
    """A single ordered research journey stage."""

    stage: str
    item: ResearchhubPost


class JourneyService:
    """Service for managing the ordered post stages in a research journey."""

    def __init__(
        self,
        journey_model: type[ResearchJourney] | None = None,
        post_model: type[ResearchhubPost] | None = None,
        unified_document_model: type[ResearchhubUnifiedDocument] | None = None,
        comment_model: type[RhCommentModel] | None = None,
        comment_thread_model: type[RhCommentThreadModel] | None = None,
        grant_application_model: type[GrantApplication] | None = None,
    ) -> None:
        """Initialize the service with optional model dependencies."""
        self.journey_model = journey_model or ResearchJourney
        self.post_model = post_model or ResearchhubPost
        self.unified_document_model = (
            unified_document_model or ResearchhubUnifiedDocument
        )
        self.comment_model = comment_model or RhCommentModel
        self.comment_thread_model = comment_thread_model or RhCommentThreadModel
        self.grant_application_model = grant_application_model or GrantApplication

    @transaction.atomic
    def get_or_create_for_preregistration(
        self, post: ResearchhubPost
    ) -> ResearchJourney:
        """Return the journey that starts from a preregistration post."""
        self._require_saved_post(post)
        if post.document_type != PREREGISTRATION:
            raise ValueError("Research journeys start from a preregistration post.")

        grant_post = self._get_grant_post_for_preregistration(post)
        journey, _ = self.journey_model.objects.get_or_create(
            preregistration_post=post,
            defaults={
                "grant_post": grant_post,
            },
        )

        update_fields = []
        if journey.grant_post_id is None and grant_post is not None:
            journey.grant_post = grant_post
            update_fields.append("grant_post")
        if update_fields:
            journey.save(update_fields=update_fields)

        self.attach_stage(journey, post)
        return journey

    def ensure_approved_preregistration_has_journey(
        self, post: ResearchhubPost
    ) -> ResearchJourney | None:
        """Create a journey for an approved preregistration, if needed."""
        if not self._is_approved_preregistration(post):
            return None
        return self.get_or_create_for_preregistration(post)

    def list_completed_proposal_candidates(
        self, user: User
    ) -> QuerySet[ResearchhubPost]:
        """Return completed proposal candidates for registered report creation."""
        completed_fundraises = Fundraise.objects.filter(
            status=Fundraise.COMPLETED,
        ).order_by("-created_date", "-id")
        registered_reports = self.post_model.objects.filter(
            document_type=REGISTERED_REPORT,
            journey_id=OuterRef("journey_id"),
        )

        return (
            self.post_model.objects.filter(
                created_by=user,
                document_type=PREREGISTRATION,
                journey_id__isnull=False,
                unified_document__fundraises__status=Fundraise.COMPLETED,
                unified_document__is_removed=False,
                unified_document__status=ResearchhubUnifiedDocument.APPROVED,
            )
            .annotate(has_registered_report=Exists(registered_reports))
            .filter(has_registered_report=False)
            .select_related("journey", "unified_document")
            .prefetch_related(
                Prefetch(
                    "unified_document__fundraises",
                    queryset=completed_fundraises,
                    to_attr="completed_fundraises",
                )
            )
            .distinct()
            .order_by("-created_date", "-id")
        )

    def get_completed_proposal_candidate(
        self, user: User, proposal_id: int
    ) -> ResearchhubPost:
        """Return one completed proposal candidate or raise a validation error."""
        proposal = self.list_completed_proposal_candidates(user).filter(
            id=proposal_id
        ).first()
        if proposal is None:
            raise ValueError("Proposal is not eligible for a registered report.")
        return proposal

    @transaction.atomic
    def create_registered_report(
        self,
        *,
        user: User,
        proposal_id: int,
        title: str,
        renderable_text: str,
        note_id: int | None = None,
        editor_type: str | None = None,
        image: str | None = None,
        preview_img: str | None = None,
    ) -> ResearchhubPost:
        """Create an approved registered report for a completed proposal."""
        proposal = self.get_completed_proposal_candidate(user, proposal_id)
        unified_document = self.unified_document_model.objects.create(
            document_type=REGISTERED_REPORT,
            is_public=True,
            status=ResearchhubUnifiedDocument.APPROVED,
        )
        unified_document.hubs.set(proposal.unified_document.hubs.all())

        registered_report = self.post_model.objects.create(
            created_by=user,
            document_type=REGISTERED_REPORT,
            editor_type=editor_type or CK_EDITOR,
            image=image,
            note_id=note_id,
            preview_img=preview_img,
            renderable_text=renderable_text,
            slug=slugify(title),
            title=title,
            unified_document=unified_document,
        )
        registered_report.authors.set(proposal.authors.all())
        self.attach_stage(proposal.journey, registered_report)
        return registered_report

    def get_owned_registered_report(
        self, user: User, registered_report_id: int
    ) -> ResearchhubPost:
        """Return an owned registered report or raise a validation error."""
        report = self.post_model.objects.filter(
            created_by=user,
            document_type=REGISTERED_REPORT,
            id=registered_report_id,
            journey_id__isnull=False,
        ).first()
        if report is None:
            raise ValueError("Registered report is not eligible for results.")
        return report

    @transaction.atomic
    def append_registered_report_results(
        self,
        *,
        user: User,
        registered_report_id: int,
        comment_content_json: object,
        comment_content_type: str | None = None,
        context_title: str | None = None,
    ) -> RhCommentModel:
        """Append results to a registered report as an author update."""
        registered_report = self.get_owned_registered_report(
            user, registered_report_id
        )
        thread = self.comment_thread_model.objects.create(
            content_type=ContentType.objects.get_for_model(registered_report),
            object_id=registered_report.id,
            thread_reference=REGISTERED_REPORT_RESULTS_REFERENCE,
            thread_type=AUTHOR_UPDATE,
        )
        comment = self.comment_model.objects.create(
            comment_content_json=comment_content_json,
            comment_content_type=comment_content_type or QUILL_EDITOR,
            comment_type=AUTHOR_UPDATE,
            context_title=context_title,
            created_by=user,
            thread=thread,
            updated_by=user,
        )
        comment.refresh_related_discussion_count()
        return comment

    @transaction.atomic
    def include_completed_fundraise_in_journal(
        self, fundraise: Fundraise
    ) -> ResearchJourney | None:
        """Include a completed fundraise's proposal journey in the journal."""
        if fundraise.status != Fundraise.COMPLETED:
            return None

        proposal = self._get_preregistration_for_fundraise(fundraise)
        if proposal is None:
            return None

        journey = self.ensure_approved_preregistration_has_journey(proposal)
        if journey is None:
            return None

        update_fields = []
        if not journey.is_in_journal:
            journey.is_in_journal = True
            update_fields.append("is_in_journal")
        if journey.journal_included_date is None:
            journey.journal_included_date = timezone.now()
            update_fields.append("journal_included_date")
        if update_fields:
            journey.save(update_fields=update_fields)

        return journey

    @transaction.atomic
    def attach_stage(
        self, journey: ResearchJourney, post: ResearchhubPost
    ) -> ResearchhubPost:
        """Attach a proposal or registered report post to a journey."""
        self._require_saved_journey(journey)
        self._require_saved_post(post)

        if post.document_type not in (PREREGISTRATION, REGISTERED_REPORT):
            raise ValueError("Only proposal and registered report posts join journeys.")
        if post.journey_id is not None and post.journey_id != journey.id:
            raise ValueError("Post already belongs to another journey.")

        if post.document_type == PREREGISTRATION:
            self._ensure_proposal_slot(journey, post)
        else:
            if self.get_proposal(journey) is None:
                raise ValueError("Journey needs a proposal before a registered report.")
            self._ensure_registered_report_slot(journey, post)

        if post.journey_id != journey.id:
            post.journey = journey
            self._save_stage_link(post)

        return post

    def get_proposal(self, journey: ResearchJourney) -> ResearchhubPost | None:
        """Return the proposal post for the journey, if one exists."""
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

    def get_registered_report(
        self, journey: ResearchJourney
    ) -> ResearchhubPost | None:
        """Return the registered report post for the journey, if one exists."""
        self._require_saved_journey(journey)
        return (
            self.post_model.objects.filter(
                journey=journey,
                document_type=REGISTERED_REPORT,
            )
            .order_by("id")
            .first()
        )

    def get_latest_stage_post(
        self, journey: ResearchJourney
    ) -> ResearchhubPost | None:
        """Return the latest available post stage in the journey."""
        return self.get_registered_report(journey) or self.get_proposal(journey)

    def get_stages(self, journey: ResearchJourney) -> list[JourneyStage]:
        """Return journey stages in journal display order."""
        self._require_saved_journey(journey)
        stages = []

        if journey.grant_post_id is not None:
            stages.append(JourneyStage(JOURNEY_STAGE_GRANT, journey.grant_post))

        proposal = self.get_proposal(journey)
        if proposal is not None:
            stages.append(JourneyStage(JOURNEY_STAGE_PROPOSAL, proposal))

        registered_report = self.get_registered_report(journey)
        if registered_report is not None:
            stages.append(
                JourneyStage(JOURNEY_STAGE_REGISTERED_REPORT, registered_report)
            )

        return sorted(stages, key=lambda stage: JOURNEY_STAGE_ORDER[stage.stage])

    def has_registered_report(self, journey: ResearchJourney) -> bool:
        """Return whether the journey has a registered report stage."""
        return self.get_registered_report(journey) is not None

    def _get_grant_post_for_preregistration(
        self, post: ResearchhubPost
    ) -> ResearchhubPost | None:
        """Return the grant post linked through the proposal's grant application."""
        application = (
            self.grant_application_model.objects.filter(preregistration_post=post)
            .select_related("grant__unified_document")
            .order_by("created_date", "id")
            .first()
        )
        if application is None:
            return None
        return (
            self.post_model.objects.filter(
                unified_document=application.grant.unified_document,
            )
            .order_by("id")
            .first()
        )

    def _get_preregistration_for_fundraise(
        self, fundraise: Fundraise
    ) -> ResearchhubPost | None:
        """Return the preregistration post funded by the fundraise."""
        return (
            self.post_model.objects.filter(
                document_type=PREREGISTRATION,
                unified_document_id=fundraise.unified_document_id,
            )
            .order_by("id")
            .first()
        )

    def _is_approved_preregistration(self, post: ResearchhubPost) -> bool:
        """Return whether the post is an approved preregistration."""
        return (
            post.document_type == PREREGISTRATION
            and post.unified_document.status == ResearchhubUnifiedDocument.APPROVED
        )

    def _ensure_proposal_slot(
        self, journey: ResearchJourney, post: ResearchhubPost
    ) -> None:
        """Validate and reserve the proposal slot for a journey."""
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

    def _ensure_registered_report_slot(
        self, journey: ResearchJourney, post: ResearchhubPost
    ) -> None:
        """Validate that the registered report slot is available."""
        registered_report = self.get_registered_report(journey)
        if registered_report is not None and registered_report.id != post.id:
            raise ValueError("Journey already has a registered report.")

    def _require_saved_post(self, post: ResearchhubPost | None) -> None:
        """Require a persisted post instance."""
        if post is None or post.pk is None:
            raise ValueError("Post must be saved.")

    def _require_saved_journey(self, journey: ResearchJourney | None) -> None:
        """Require a persisted journey instance."""
        if journey is None or journey.pk is None:
            raise ValueError("Journey must be saved.")

    def _save_stage_link(self, post: ResearchhubPost) -> None:
        """Persist a post-to-journey link and normalize duplicate report errors."""
        try:
            with transaction.atomic():
                post.save(update_fields=["journey"])
        except IntegrityError as error:
            if post.document_type == REGISTERED_REPORT:
                raise ValueError("Journey already has a registered report.") from error
            raise
