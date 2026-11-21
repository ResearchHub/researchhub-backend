"""
Ranking for proposals under one RFP.

Proposals are ordered by strict tiers. Each tier only breaks ties left by the
tiers above it, so a funded proposal always stays above an unfunded one, no
matter its reviews or upvotes.

1. Fundraise open first, then everything else (closed, or no fundraise).
2. Amount raised, highest first: escrowed RSC (``amount_holding +
   amount_paid``), the same amount the ``amount_raised`` ordering uses.
3. Review score, highest first: the plain average of assessed reviews.
   Proposals without assessed reviews count as 0.
4. Upvotes (the post's vote score), highest first.
5. Newest first.

The same rule is applied in SQL (``funding_feed?grant_id=<id>&ordering=best``) and in
Python (applications nested in grant payloads).
"""

from collections.abc import Iterable
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import (
    Avg,
    Case,
    DecimalField,
    Exists,
    F,
    FloatField,
    IntegerField,
    OuterRef,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
    prefetch_related_objects,
)
from django.db.models.functions import Coalesce

from purchase.related_models.fundraise_model import Fundraise
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from review.models import Review

STATUS_OPEN = 0
STATUS_NOT_OPEN = 1

_AMOUNT_FIELD = DecimalField(max_digits=19, decimal_places=10)


def assessed_review_queryset() -> QuerySet:
    """Reviews that count toward a proposal's score."""
    active_comment = RhCommentModel.objects.filter(
        id=OuterRef("object_id"), is_removed=False
    )
    return Review.objects.filter(
        is_removed=False,
        is_assessed=True,
        content_type=ContentType.objects.get_for_model(RhCommentModel),
    ).filter(Exists(active_comment))


class ProposalRankingService:
    @staticmethod
    def status_bucket(fundraise: Fundraise | None) -> int:
        if fundraise is not None and fundraise.status == Fundraise.OPEN:
            return STATUS_OPEN
        return STATUS_NOT_OPEN

    @staticmethod
    def amount_raised(fundraises: Iterable[Fundraise]) -> Decimal:
        total = Decimal(0)
        for fundraise in fundraises:
            escrow = fundraise.escrow
            if escrow is not None:
                total += escrow.amount_holding + escrow.amount_paid
        return total

    @staticmethod
    def review_score(reviews: Iterable[Review]) -> float:
        scores = [
            review.score
            for review in reviews
            if review.is_assessed and not review.is_removed and review.score is not None
        ]
        return sum(scores) / len(scores) if scores else 0.0

    def sort_key(self, post, fundraises: list[Fundraise], reviews) -> tuple:
        """Ascending sort key; lower sorts first."""
        created = post.created_date.timestamp() if post.created_date else 0.0
        return (
            self.status_bucket(fundraises[0] if fundraises else None),
            -self.amount_raised(fundraises),
            -self.review_score(reviews),
            -(post.score or 0),
            -created,
        )

    def sort_grant_applications(self, applications: Iterable) -> list:
        """Order a grant's applications by the ranking."""
        applications = list(applications)
        prefetch_related_objects(
            applications,
            "preregistration_post__unified_document__fundraises__escrow",
            "preregistration_post__unified_document__reviews",
        )
        keyed = []
        for application in applications:
            post = application.preregistration_post
            ud = getattr(post, "unified_document", None) if post else None
            if post is None or ud is None:
                keyed.append(((STATUS_NOT_OPEN + 1,), application))
                continue
            key = self.sort_key(post, list(ud.fundraises.all()), ud.reviews.all())
            keyed.append((key, application))
        keyed.sort(key=lambda pair: pair[0])
        return [application for _, application in keyed]

    def order_posts(self, queryset: QuerySet) -> QuerySet:
        has_open_fundraise = Exists(
            Fundraise.objects.filter(
                unified_document_id=OuterRef("unified_document_id"),
                status=Fundraise.OPEN,
            )
        )
        amount_raised = (
            Fundraise.objects.filter(
                unified_document_id=OuterRef("unified_document_id")
            )
            .values("unified_document_id")
            .annotate(total=Sum(F("escrow__amount_holding") + F("escrow__amount_paid")))
            .values("total")
        )
        review_score = (
            assessed_review_queryset()
            .filter(unified_document_id=OuterRef("unified_document_id"))
            .values("unified_document_id")
            .annotate(avg=Avg("score"))
            .values("avg")
        )

        return queryset.annotate(
            ranking_status=Case(
                When(has_open_fundraise, then=Value(STATUS_OPEN)),
                default=Value(STATUS_NOT_OPEN),
                output_field=IntegerField(),
            ),
            ranking_amount_raised=Coalesce(
                Subquery(amount_raised, output_field=_AMOUNT_FIELD),
                Value(0),
                output_field=_AMOUNT_FIELD,
            ),
            ranking_review_score=Coalesce(
                Subquery(review_score, output_field=FloatField()),
                Value(0.0),
                output_field=FloatField(),
            ),
            ranking_upvotes=Coalesce(F("score"), Value(0)),
        ).order_by(
            "ranking_status",
            "-ranking_amount_raised",
            "-ranking_review_score",
            "-ranking_upvotes",
            "-created_date",
        )
