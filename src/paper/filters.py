from django_filters import rest_framework as filters
from .models import Paper


class PaperFilter(filters.FilterSet):
    hubs_id__in = filters.Filter(field_name="hubs", lookup_expr='in')

    class Meta:
        model = Paper
        # TODO: Handle filtering on raw_authors in another way
        exclude = [
            'alternate_ids',
            'file',
            'csl_item',
            'oa_pdf_location',
            'raw_authors',
        ]
