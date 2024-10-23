from django.db.models import Prefetch, Q
from django_filters import rest_framework as filters

from hub.models import Hub
from paper.models import Figure
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    BOUNTY,
    DISCUSSION,
    ELN,
    NOTE,
    PAPER,
    POSTS,
    PREREGISTRATION,
    QUESTION,
)
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    EXPIRING_SOON,
    HOT,
    MOST_RSC,
    NEW,
    UPVOTED,
)
from researchhub_document.utils import get_date_ranges_by_time_scope
from review.models import Review

DOC_CHOICES = (
    ("all", "All"),
    ("paper", "Papers"),
    ("posts", "Posts"),
    ("question", "Questions"),
    ("bounty", "Bounty"),
    ("preregistration", "Preregistration"),
)
TAG_CHOICES = (
    ("answered", "Answered"),
    ("author_claimed", "Author Claimed"),
    ("closed", "Closed"),
    ("expired", "Expired"),
    ("open", "Open"),
    ("open_access", "Open Access"),
    ("peer_reviewed", "Peer Reviewed"),
    ("unanswered", "Unanswered"),
)
TAG_CHOICES_STR = (
    "answered",
    "author_claimed",
    "closed",
    "expired",
    "open",
    "open_access",
    "peer_reviewed",
    "unanswered",
)
ORDER_CHOICES = (
    (NEW, "New"),
    (HOT, "Hot"),
    (DISCUSSED, "Discussed"),
    (UPVOTED, "Upvoted"),
    (EXPIRING_SOON, "Expiring Soon"),
    (MOST_RSC, "Most RSC"),
)
TIME_SCOPE_CHOICES = ("today", "week", "month", "year", "all")


class UnifiedDocumentFilter(filters.FilterSet):
    hub_id = filters.ModelChoiceFilter(
        field_name="hubs",
        queryset=Hub.objects.all(),
        label="Hubs",
    )
    type = filters.ChoiceFilter(
        field_name="document_type",
        method="document_type_filter",
        choices=DOC_CHOICES,
        null_value="all",
    )
    tags = filters.CharFilter(method="tag_filter", label="Tags")
    subscribed_hubs = filters.BooleanFilter(
        method="subscribed_filter",
        label="Subscribed Hubs",
    )
    ignore_excluded_homepage = filters.BooleanFilter(
        method="exclude_feed_filter",
        label="Excluded documents",
    )

    class Meta:
        model = ResearchhubUnifiedDocument
        fields = [
            "hub_id",
            "subscribed_hubs",
            "type",
            "ignore_excluded_homepage",
        ]

    def _map_tag_to_document_filter(self, value):
        if value == "closed":
            return "bounty_closed", True
        elif value == "expired":
            return "bounty_expired", True
        elif value == "open":
            return "bounty_open", True
        elif value == "unanswered":
            return "answered", False
        return value, True

    def document_type_filter(self, qs, name, value):
        value = value.upper()
        selects = (
            "document_filter",
            "paper",
            "paper__uploaded_by",
            "paper__uploaded_by__author_profile",
        )
        prefetches = (
            "hubs",
            "paper__authors",
            Prefetch(
                "paper__figures",
                queryset=Figure.objects.filter(figure_type=Figure.PREVIEW),
            ),
            "paper__hubs",
            "paper__purchases",
            "paper__figures",
            "posts",
            "posts__authors",
            "posts__created_by",
            "posts__created_by__author_profile",
            "posts__purchases",
            "posts__threads",
            Prefetch("reviews", queryset=Review.objects.filter(is_removed=False)),
            "related_bounties",
        )

        if value == PAPER:
            qs = qs.filter(document_type=PAPER)
            selects = (
                "document_filter",
                "paper",
                "paper__uploaded_by",
                "paper__uploaded_by__author_profile",
            )
            prefetches = (
                "hubs",
                "paper",
                "paper__authors",
                "fundraises",
                Prefetch(
                    "paper__figures",
                    queryset=Figure.objects.filter(figure_type=Figure.PREVIEW),
                ),
                Prefetch("reviews", queryset=Review.objects.filter(is_removed=False)),
                "related_bounties",
                "paper__hubs",
                "paper__figures",
                "paper__purchases",
            )
        elif value == POSTS:
            qs = qs.filter(document_type__in=[DISCUSSION, ELN])
            selects = ["document_filter"]
            prefetches = [
                "hubs",
                Prefetch("reviews", queryset=Review.objects.filter(is_removed=False)),
                "related_bounties",
                "posts",
                "posts__authors",
                "posts__created_by",
                "posts__created_by__author_profile",
                "posts__purchases",
            ]
        elif value == QUESTION:
            qs = qs.filter(document_type=QUESTION)
            selects = ["document_filter"]
        elif value == PREREGISTRATION:
            qs = qs.filter(document_type=PREREGISTRATION)
            selects = ["document_filter"]
        elif value == BOUNTY:
            prefetches = (
                "hubs",
                Prefetch("reviews", queryset=Review.objects.filter(is_removed=False)),
                "related_bounties",
            )
            qs = qs.filter(document_filter__has_bounty=True)
        else:
            # We do this for preregistrations so that they don't show up in the home feed,
            # but do show up on the /funding page.
            # This is a temporary solution as we trial out preregistration funding.
            qs = qs.exclude(document_type__in=[NOTE, PREREGISTRATION])

        return qs.select_related(*selects).prefetch_related(*prefetches)

    def tag_filter(self, qs, name, values):
        tags = values.split(",")
        queries = Q()
        for value in tags:
            if value in TAG_CHOICES_STR:
                key, value = self._map_tag_to_document_filter(value)
                queries &= Q(**{f"document_filter__{key}": value})

        qs = qs.filter(queries)
        return qs

    def exclude_feed_filter(self, qs, name, values):
        qs = qs.exclude(document_filter__is_excluded_in_feed=True)
        return qs

    def subscribed_filter(self, qs, name, value):
        if value and self.request.user.is_anonymous is not True:
            user = self.request.user
            hub_ids = user.subscribed_hubs.values_list("id", flat=True)
            qs = qs.filter(hubs__in=hub_ids)
        return qs
