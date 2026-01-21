from functools import reduce

from django.contrib.contenttypes.models import ContentType
from django.db.models import DecimalField, Exists, IntegerField, OuterRef, Q, Sum
from django.db.models.functions import Cast, Coalesce
from django_filters import DateTimeFilter
from django_filters import rest_framework as filters

from reputation.models import Bounty
from researchhub_access_group.constants import PRIVATE, PUBLIC, WORKSPACE
from researchhub_comment.constants.rh_comment_thread_types import (
    AUTHOR_UPDATE,
    GENERIC_COMMENT,
    INNER_CONTENT_COMMENT,
    RH_COMMENT_THREAD_TYPES,
    SUMMARY,
)
from researchhub_comment.models import RhCommentModel
from utils.http import GET

BEST = "BEST"
TOP = "TOP"
BOUNTY = "BOUNTY"
REVIEW = "REVIEW"
PEER_REVIEW = "PEER_REVIEW"
DISCUSSION = "DISCUSSION"
REPLICABILITY_COMMENT = "REPLICABILITY_COMMENT"
CREATED_DATE = "CREATED_DATE"

ORDER_CHOICES = (
    (BEST, "Best"),
    (TOP, "Top"),
    (CREATED_DATE, "Created Date"),
)

PRIVACY_CHOICES = (
    (PUBLIC, "Public comments"),
    (PRIVATE, "Private comments"),
    (WORKSPACE, "Organization comments"),
)

FILTER_CHOICES = (
    (BOUNTY, "Has Bounty"),
    (REVIEW, REVIEW),
    (PEER_REVIEW, PEER_REVIEW),
    (DISCUSSION, DISCUSSION),
    (REPLICABILITY_COMMENT, REPLICABILITY_COMMENT),
    (INNER_CONTENT_COMMENT, INNER_CONTENT_COMMENT),
    (AUTHOR_UPDATE, AUTHOR_UPDATE),
)


class RHCommentFilter(filters.FilterSet):
    created_date__gte = DateTimeFilter(
        field_name="created_date",
        lookup_expr="gte",
    )
    created_date__lt = DateTimeFilter(
        field_name="created_date",
        lookup_expr="lt",
    )
    updated_date__gte = DateTimeFilter(
        field_name="updated_date",
        lookup_expr="gte",
    )
    updated_date__lt = DateTimeFilter(
        field_name="updated_date",
        lookup_expr="lt",
    )
    ordering = filters.ChoiceFilter(
        method="ordering_filter",
        choices=ORDER_CHOICES,
        null_value=BEST,
        label="Ordering",
    )
    filtering = filters.ChoiceFilter(
        method="filtering_filter",
        choices=FILTER_CHOICES,
        label="Filter by",
    )
    child_count = filters.NumberFilter(
        method="filter_child_count",
        label="Child Comment Count",
    )
    thread_type = filters.ChoiceFilter(
        choices=RH_COMMENT_THREAD_TYPES,
        field_name="thread__thread_type",
        label="Thread Type",
    )
    privacy_type = filters.ChoiceFilter(
        choices=PRIVACY_CHOICES, method="privacy_filter", label="Privacy Filter"
    )
    parent__isnull = filters.BooleanFilter(
        field_name="parent__isnull", method="filtering_parent"
    )
    ascending = filters.BooleanFilter(
        method="handle_ascending", label="Sort order ascending"
    )

    class Meta:
        model = RhCommentModel
        fields = ("ordering",)

    def __init__(self, *args, request=None, **kwargs):
        # Privacy type should always be set, even if not passed in
        # This will ensure private/organization comments will be hidden
        if request.method == GET:
            kwargs["data"]._mutable = True
            if "privacy_type" not in kwargs["data"]:
                kwargs["data"]["privacy_type"] = PUBLIC
            kwargs["data"]._mutable = False
        super().__init__(*args, request=request, **kwargs)

    def _is_ascending(self):
        # BooleanFilter automatically converts "true"/"false" strings to boolean
        # Default to False (descending) if not provided
        return (
            self.form.cleaned_data.get("ascending", False)
            if hasattr(self, "form") and self.form.is_valid()
            else False
        )

    def handle_ascending(self, qs, name, value):
        # This method is called by the BooleanFilter but we don't need to do anything here
        # The actual ordering is handled in ordering_filter
        return qs

    def _get_ordering_keys(self, keys):
        if not self._is_ascending():
            return [f"-{key}" for key in keys]
        return keys

    def _annotate_bounty_sum(self, qs, annotation_filters=None):
        annotation_filters = [] if annotation_filters is None else annotation_filters
        annotation_filters_query = reduce(
            lambda q, value: q | Q(**value), annotation_filters, Q()
        )
        queryset = qs.annotate(
            bounty_sum=Coalesce(
                Sum("bounties__amount", filter=annotation_filters_query),
                0,
                output_field=DecimalField(max_digits=19, decimal_places=10),
            )
        )
        return queryset

    def _order_by_scores(self, qs, sort_key):
        from researchhub_comment.scoring import CommentScorer
        from django.db.models import Case, When, Value
        from purchase.models import Purchase
        from reputation.models import BountySolution
        
        annotated_qs = qs.select_related('created_by').annotate(
            tip_amount=Sum(
                Case(
                    When(
                        purchases__purchase_type=Purchase.BOOST,
                        purchases__paid_status=Purchase.PAID,
                        then=Cast('purchases__amount', DecimalField(max_digits=19, decimal_places=10))
                    ),
                    default=Value(0),
                    output_field=DecimalField(max_digits=19, decimal_places=10)
                )
            ),
            bounty_award_amount=Sum(
                Case(
                    When(
                        bounty_solution__status=BountySolution.Status.AWARDED,
                        then='bounty_solution__awarded_amount'
                    ),
                    default=Value(0),
                    output_field=DecimalField(max_digits=19, decimal_places=10)
                )
            )
        )
        
        scored_items = []
        for comment in annotated_qs:
            is_verified = comment.created_by.is_verified if comment.created_by else False
            
            score_data = CommentScorer.calculate_score(comment, {
                'tip_amount': float(getattr(comment, 'tip_amount', 0) or 0),
                'bounty_award_amount': float(getattr(comment, 'bounty_award_amount', 0) or 0),
                'is_verified_user': is_verified
            })
            scored_items.append((comment.id, sort_key(comment, score_data['score'])))
        
        if not scored_items:
            return qs
        
        scored_items.sort(key=lambda x: x[1], reverse=True)
        
        ordering = Case(
            *[When(pk=item_id, then=Value(pos)) for pos, (item_id, _) in enumerate(scored_items)],
            output_field=IntegerField()
        )
        
        sorted_ids = [item_id for item_id, _ in scored_items]
        return qs.filter(pk__in=sorted_ids).order_by(ordering)

    def _apply_academic_ordering(self, qs):
        return self._order_by_scores(qs, lambda c, score: score)

    def _apply_bounty_ordering(self, qs):
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        qs = qs.annotate(
            has_open_bounty=Exists(
                Bounty.objects.filter(
                    item_content_type=comment_ct,
                    item_object_id=OuterRef("id"),
                    status=Bounty.OPEN,
                )
            )
        )
        return self._order_by_scores(qs, 
            lambda c, score: (getattr(c, 'has_open_bounty', False), score)
        )

    def _is_on_child_queryset(self):
        # This checks whether we are filtering on the comment's children
        # because we don't want the related filters to be called
        # on the base comments, only children
        instance_class_name = self.queryset.__class__.__name__
        if instance_class_name == "RelatedManager":
            return True

    def _has_explicit_filtering(self):
        """
        Return True if an explicit `filtering` parameter was supplied by the client.
        """
        return bool(self.data.get("filtering"))

    @property
    def qs(self):
        """
        Override the default queryset evaluation.
        It applies a *default* filter when the client has not explicitly provided
        the ``filtering`` query parameter.
        The default behaviour should return only GENERIC_COMMENT comments that do
        **not** have any bounties attached. This excludes REVIEW / PEER_REVIEW
        comments and comments with bounties.
        This keeps the response focused on general discussion by default.
        """
        # Start with the base queryset that Django-Filters builds using the
        # declared filters (ordering, privacy, explicit filtering, etc.).
        base_qs = super().qs

        # If we're on a RelatedManager (children queryset) or the caller explicitly
        # requested a filtering, respect that request and return the queryset
        # unmodified.
        if self._is_on_child_queryset() or self._has_explicit_filtering():
            return base_qs

        # Apply the default restriction: include only comments whose own
        # `comment_type` and their parent thread's `thread_type` are both
        # GENERIC_COMMENT, and that do **not** have bounties attached.
        return base_qs.filter(
            comment_type=GENERIC_COMMENT,
            thread__thread_type=GENERIC_COMMENT,
            bounties__isnull=True,
            parent__isnull=True,
        )

    def ordering_filter(self, qs, name, value):
        if value == BEST:
            return self._apply_academic_ordering(qs)
        elif value == TOP:
            keys = self._get_ordering_keys(["score"])
            qs = qs.order_by(*keys)
        elif value == BOUNTY:
            qs = self._annotate_bounty_sum(qs).filter(bounty_sum__gt=0)
            return self._apply_bounty_ordering(qs)
        elif value == CREATED_DATE:
            keys = self._get_ordering_keys(["created_date"])
            qs = qs.order_by(*keys)
        return qs

    def filtering_filter(self, qs, name, value):
        if self._is_on_child_queryset():
            return qs

        if value == BOUNTY:
            qs = qs.filter(bounties__isnull=False)
            qs = self._annotate_bounty_sum(
                qs, annotation_filters=[{"bounties__status": Bounty.OPEN}]
            )
        elif value == REVIEW:
            qs = qs.filter(comment_type__in=[REVIEW, PEER_REVIEW])
        elif value == INNER_CONTENT_COMMENT:
            qs = qs.filter(comment_type=INNER_CONTENT_COMMENT)
        elif value == DISCUSSION:
            qs = qs.filter(
                (Q(comment_type=GENERIC_COMMENT) & Q(bounties__isnull=True))
                | Q(comment_type=SUMMARY)
                | Q(comment_type=INNER_CONTENT_COMMENT)
            )
        elif value == REPLICABILITY_COMMENT:
            qs = qs.filter(thread__thread_type=REPLICABILITY_COMMENT)
        elif value == "AUTHOR_UPDATE":
            qs = qs.filter(thread__thread_type=AUTHOR_UPDATE)

        return qs

    def filter_child_count(self, qs, name, value):
        if not self._is_on_child_queryset():
            return qs
        offset = int(self.data.get("child_offset", 0))
        count = offset + value

        # Returning the slice qs[offset:count] will cause an error
        # if the queryset has additional filtering
        sliced_children_ids = qs[offset:count].values_list("id")
        return qs.filter(id__in=sliced_children_ids)

    def privacy_filter(self, qs, name, value):
        request = self.request
        user = request.user

        if user.is_anonymous:
            return qs.filter(thread__permissions__isnull=True)

        if value == PRIVATE:
            qs = qs.filter(
                thread__permissions__user=user,
                thread__permissions__organization__isnull=True,
            )
        elif value == WORKSPACE:
            # Organization permission check is done in permissions
            org = request.organization
            qs = qs.filter(
                thread__permissions__organization=org,
                thread__permissions__organization__isnull=False,
            )
        else:
            # Public comments
            qs = qs.filter(thread__permissions__isnull=True)
        return qs

    def filtering_parent(self, qs, name, value):
        if self._is_on_child_queryset():
            return qs

        # Simply filter by parent__isnull without creating a new queryset
        # This preserves any ordering that was previously applied
        return qs.filter(parent__isnull=value)
