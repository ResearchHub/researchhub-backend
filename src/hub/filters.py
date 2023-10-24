from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import FileField
from django_filters import rest_framework as filters

from .models import Hub


class HubFilter(filters.FilterSet):
    name__iexact = filters.Filter(field_name="name", lookup_expr="iexact")
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
