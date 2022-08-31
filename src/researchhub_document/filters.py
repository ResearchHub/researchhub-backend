from django.db.models import Count, Q
from django_filters import rest_framework as filters

from hub.models import Hub
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    ELN,
    HYPOTHESIS,
    NOTE,
    PAPER,
    POSTS,
    QUESTION,
)
from researchhub_document.utils import get_date_ranges_by_time_scope

DOC_CHOICES = (
    ("all", "All"),
    ("paper", "Papers"),
    ("posts", "Posts"),
    ("hypothesis", "Hypothesis"),
    ("question", "Questions"),
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
ORDER_CHOICES = (
    ("new", "New"),
    ("hot", "Hot"),
    ("discussed", "Discussed"),
    ("upvoted", "Upvoted"),
    ("expiring_soon", "Expiring Soon"),
    ("most_rsc", "Most RSC"),
)
TIME_SCOPE_CHOICES = ("today", "week", "month", "year", "all")
# BOUNTY_CHOICES = (
#     ("all", "All"),
#     ("none", "None")
#     # ("open", "Open"),
#     # ("cancelled", "Cancelled"),
#     # ("expired", "Expired"),
#     # ("closed", "Closed"),
# )


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
    tags = filters.MultipleChoiceFilter(
        method="tag_filter", label="Tags", choices=TAG_CHOICES
    )

    ordering = filters.ChoiceFilter(
        method="ordering_filter",
        choices=ORDER_CHOICES,
        label="Ordering",
    )
    subscribed_hubs = filters.BooleanFilter(
        method="subscribed_filter",
        label="Subscribed Hubs",
    )
    # bounties = filters.ChoiceFilter(
    #     field_name="bounties",
    #     method="bounty_type_filter",
    #     choices=BOUNTY_CHOICES,
    # )

    class Meta:
        model = ResearchhubUnifiedDocument
        fields = ["hub_id", "ordering", "subscribed_hubs", "type"]

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

        if value == PAPER:
            qs = qs.filter(document_type=PAPER)
        elif value == POSTS:
            qs = qs.filter(document_type__in=[DISCUSSION, ELN])
        elif value == QUESTION:
            qs = qs.filter(document_type=QUESTION)
        elif value == HYPOTHESIS:
            qs = qs.filter(document_type=HYPOTHESIS).prefetch_related(
                "hypothesis__votes", "hypothesis__citations"
            )
        else:
            qs = qs.exclude(document_type=NOTE)
        return qs

    def tag_filter(self, qs, name, values):
        queries = Q()
        for value in values:
            key, value = self._map_tag_to_document_filter(value)
            queries |= Q(**{f"document_filter__{key}": value})

        return qs.filter(queries)

    def ordering_filter(self, qs, name, value):
        time_scope = self.data.get("time", "today")
        start_date, end_date = get_date_ranges_by_time_scope(time_scope)

        if time_scope not in TIME_SCOPE_CHOICES:
            time_scope = "today"

        ordering = []
        if value == "new":
            qs = qs.filter(document_filter__created_date__range=(start_date, end_date))
            ordering.append("-document_filter__created_date")
        elif value == "hot":
            ordering.append("-hot_score_v2")
        elif value == "discussed":
            qs = qs.filter(
                document_filter__discussed_date__range=(start_date, end_date)
            )
            ordering.append(f"-document_filter__discussed_{time_scope}")
        elif value == "upvoted":
            qs = qs.filter(document_filter__upvoted_date__range=(start_date, end_date))
            ordering.append(f"-document_filter__upvoted_{time_scope}")
        elif value == "expiring_soon":
            ordering.append("-document_filter__bounty_expiration_date")
        elif value == "most_rsc":
            ordering.append("-document_filter__bounty_total_amount")

        qs = qs.order_by(*ordering)
        return qs

    def default_filter(self, qs, name, value):
        time_scope = self.data.get("time", "today")
        start_date, end_date = get_date_ranges_by_time_scope(time_scope)
        ordering = []

        if value == "removed":
            qs = qs.filter(is_removed=True)
            ordering.append("-created_date")
        elif value == "top_rated":
            qs = qs.filter(
                Q(paper__votes__created_date__range=(start_date, end_date))
                | Q(hypothesis__votes__created_date__range=(start_date, end_date))
                | Q(posts__votes__created_date__range=(start_date, end_date))
            ).distinct()
            filtering = "-score"
            ordering.append(filtering)
        elif value == "most_discussed":
            filtering = "-discussed"
            paper_threads_Q = Q(
                paper__threads__created_date__range=[start_date, end_date],
                paper__threads__is_removed=False,
                paper__threads__created_by__isnull=False,
            )

            paper_comments_Q = Q(
                paper__threads__comments__created_date__range=[start_date, end_date],
                paper__threads__comments__is_removed=False,
                paper__threads__comments__created_by__isnull=False,
            )

            paper_replies_Q = Q(
                paper__threads__comments__replies__created_date__range=[
                    start_date,
                    end_date,
                ],
                paper__threads__comments__replies__is_removed=False,
                paper__threads__comments__replies__created_by__isnull=False,
            )

            # Posts
            post_threads_Q = Q(
                posts__threads__created_date__range=[start_date, end_date],
                posts__threads__is_removed=False,
                posts__threads__created_by__isnull=False,
            )

            post_comments_Q = Q(
                posts__threads__comments__created_date__range=[start_date, end_date],
                posts__threads__comments__is_removed=False,
                posts__threads__comments__created_by__isnull=False,
            )

            post_replies_Q = Q(
                posts__threads__comments__replies__created_date__range=[
                    start_date,
                    end_date,
                ],
                posts__threads__comments__replies__is_removed=False,
                posts__threads__comments__replies__created_by__isnull=False,
            )

            # Hypothesis
            hypothesis_threads_Q = Q(
                posts__threads__created_date__range=[start_date, end_date],
                posts__threads__is_removed=False,
                posts__threads__created_by__isnull=False,
            )

            hypothesis_comments_Q = Q(
                posts__threads__comments__created_date__range=[start_date, end_date],
                posts__threads__comments__is_removed=False,
                posts__threads__comments__created_by__isnull=False,
            )

            hypothesis_replies_Q = Q(
                posts__threads__comments__replies__created_date__range=[
                    start_date,
                    end_date,
                ],
                posts__threads__comments__replies__is_removed=False,
                posts__threads__comments__replies__created_by__isnull=False,
            )

            paper_threads_count = Count(
                "paper__threads", distinct=True, filter=paper_threads_Q
            )
            paper_comments_count = Count(
                "paper__threads__comments", distinct=True, filter=paper_comments_Q
            )
            paper_replies_count = Count(
                "paper__threads__comments__replies",
                distinct=True,
                filter=paper_replies_Q,
            )
            # Posts
            post_threads_count = Count(
                "posts__threads", distinct=True, filter=post_threads_Q
            )
            post_comments_count = Count(
                "posts__threads__comments", distinct=True, filter=post_comments_Q
            )
            post_replies_count = Count(
                "posts__threads__comments__replies",
                distinct=True,
                filter=post_replies_Q,
            )
            # Hypothesis
            hypothesis_threads_count = Count(
                "hypothesis__threads", distinct=True, filter=hypothesis_threads_Q
            )
            hypothesis_comments_count = Count(
                "hypothesis__threads__comments",
                distinct=True,
                filter=hypothesis_comments_Q,
            )
            hypothesis_replies_count = Count(
                "hypothesis__threads__comments__replies",
                distinct=True,
                filter=hypothesis_replies_Q,
            )

            qs = qs.filter(
                paper_threads_Q
                | paper_comments_Q
                | paper_replies_Q
                | post_threads_Q
                | post_comments_Q
                | post_replies_Q
                | hypothesis_threads_Q
                | hypothesis_comments_Q
                | hypothesis_replies_Q
            ).annotate(
                # Papers
                paper_threads_count=paper_threads_count,
                paper_comments_count=paper_comments_count,
                paper_replies_count=paper_replies_count,
                # Posts
                post_threads_count=post_threads_count,
                post_comments_count=post_comments_count,
                post_replies_count=post_replies_count,
                # # Hypothesis
                hypothesis_threads_count=hypothesis_threads_count,
                hypothesis_comments_count=hypothesis_comments_count,
                hypothesis_replies_count=hypothesis_replies_count,
                # # Add things up
                discussed=(
                    paper_threads_count
                    + paper_comments_count
                    + paper_replies_count
                    + post_threads_count
                    + post_comments_count
                    + post_replies_count
                    + hypothesis_threads_count
                    + hypothesis_comments_count
                    + hypothesis_replies_count
                ),
            )
            ordering.append(filtering)
        elif value == "newest":
            filtering = "-created_date"
            ordering.append(filtering)
        elif value == "author_claimed":
            qs = qs.filter(
                Q(
                    paper__related_claim_cases__isnull=False,
                    paper__related_claim_cases__status="APPROVED",
                )
            )
            filtering = "author_claimed"
            ordering.append("-hot_score_v2")
        elif value == "is_open_access":
            qs = qs.filter(
                Q(
                    paper__is_open_access=True,
                    created_date__range=(start_date, end_date),
                )
            )
            filtering = "is_open_access"
            ordering.append("-hot_score_v2")
        elif value == "hot":
            ordering.append("-hot_score_v2")
        else:
            filtering = "-score"
            ordering.append(filtering)

        qs = qs.order_by(*ordering)
        return qs

    def subscribed_filter(self, qs, name, value):
        if value and self.request.user.is_anonymous is not True:
            user = self.request.user
            hub_ids = user.subscribed_hubs.values_list("id", flat=True)
            qs = qs.filter(hubs__in=hub_ids)
        return qs

    def bounty_type_filter(self, qs, name, value):
        if value == "all":
            qs = qs.filter(related_bounties__status="OPEN")
        else:
            qs = qs.filter(related_bounties__isnull=True)
        # Using distinct() is not ideal
        return qs.distinct()
