from datetime import timedelta

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Count, F, FileField, Q
from django.utils import timezone
from django_filters import rest_framework as filters

from discussion.reaction_models import Vote

from .models import Hub


class ScoreOrderingFilter(filters.OrderingFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extra["choices"] += ["score", "-score"]

    def filter(self, qs, value):
        if value and any(v in ["score", "-score"] for v in value):
            two_weeks_ago = timezone.now().date() - timedelta(days=14)
            num_upvotes = Count(
                "papers__votes__vote_type",
                filter=Q(
                    papers__votes__vote_type=Vote.UPVOTE,
                    papers__votes__created_date__gte=two_weeks_ago,
                ),
            )
            num_downvotes = Count(
                "papers__votes__vote_type",
                filter=Q(
                    papers__votes__vote_type=Vote.DOWNVOTE,
                    papers__votes__created_date__gte=two_weeks_ago,
                ),
            )

            DISCUSSION_FACTOR = 10
            score = (
                (num_upvotes - num_downvotes)
                + DISCUSSION_FACTOR * F("discussion_count")
                + F("paper_count")
            )

            qs = qs.annotate(score=score).order_by(*value, "id")
            return qs

        else:
            return super().filter(qs, value)


class HubFilter(filters.FilterSet):
    name__iexact = filters.Filter(field_name="name", lookup_expr="iexact")
    ordering = ScoreOrderingFilter(fields=["name", "score"])
    name__fuzzy = filters.Filter(
        field_name="name", method="name_trigram_similarity_search"
    )

    class Meta:
        model = Hub
        fields = [field.name for field in model._meta.fields]
        filter_overrides = {
            FileField: {
                "filter_class": filters.CharFilter,
            }
        }

    def name_trigram_similarity_search(self, qs, name, value):
        qs = qs.annotate(similarity=TrigramSimilarity(name, value)).filter(
            similarity__gt=0.15
        )
        qs = qs.order_by("-similarity")
        return qs
