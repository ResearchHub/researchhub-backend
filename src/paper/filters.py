from django_filters import rest_framework as filters
from .models import Paper


class PaperFilter(filters.FilterSet):
    hubs_id__in = filters.Filter(field_name="hubs", lookup_expr='in')

    class Meta:
        model = Paper
        exclude = ['file', 'csl_item', 'pdf_location']
