from django.db.models import Count, Q
from django_filters import rest_framework as filters

from hub.models import Hub
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    ELN,
    HYPOTHESIS,
    PAPER,
    POSTS,
)
from researchhub_document.utils import get_date_ranges_by_time_scope

DOC_CHOICES = (
    ("all", "All"),
    ("papers", "Papers"),
    ("posts", "Posts"),
    ("hypothesis", "Hypothesis"),
)
UNIFIED_DOCUMENT_FILTER_CHOICES = (
    ("removed", "Removed"),
    ("top_rated", "Top Rated"),
    ("most_discussed", "Most Discussed"),
    ("newest", "Newest"),
    ("hot", "Hot"),
)


class FlagDashboardFilter(filters.FilterSet):
    hub_id = filters.ModelChoiceFilter(
        field_name="hubs",
        queryset=Hub.objects.all(),
        label="Hubs",
    )
    type = filters.ChoiceFilter(
        field_name="document_type",
        method="document_type_filter",
        choices=DOC_CHOICES,
    )
    ordering = filters.ChoiceFilter(
        method="default_filter",
        choices=UNIFIED_DOCUMENT_FILTER_CHOICES,
        label="Ordering",
    )
    subscribed_hubs = filters.BooleanFilter(
        method="subscribed_filter",
        label="Subscribed Hubs",
    )

    class Meta:
        model = ResearchhubUnifiedDocument
        fields = ["hub_id", "ordering", "subscribed_hubs"]

    def document_type_filter(self, qs, name, value):
        value = value.upper()
        if value == PAPER:
            qs = qs.filter(document_type=PAPER)
        elif value == POSTS:
            qs = qs.filter(document_type__in=[DISCUSSION, ELN])
        elif value == HYPOTHESIS:
            qs = qs.filter(document_type=HYPOTHESIS).prefetch_related(
                "hypothesis__votes", "hypothesis__citations"
            )
        return qs

    def default_filter(self, qs, name, value):
        time_scope = self.data.get("time", "today")
        start_date, end_date = get_date_ranges_by_time_scope(time_scope)
        ordering = []

        if value == "removed":
            qs = qs.filter(is_removed=True)
            ordering.append("-created_date")
        elif value == "top_rated":
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
        elif value == "hot":
            filtering = "-hot_score"
            ordering.append("featured_in_hubs")
            ordering.append("-hot_score_v2")
        else:
            filtering = "-score"
            ordering.append(filtering)

        return qs.order_by(*ordering)

    def subscribed_filter(self, qs, name, value):
        if value:
            user = self.request.user
            hub_ids = user.subscribed_hubs.values_list("id", flat=True)
            qs = qs.filter(hubs__in=hub_ids)
        return qs
