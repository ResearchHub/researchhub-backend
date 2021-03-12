from django_filters import rest_framework as filters
from .models import Paper


class PaperFilter(filters.FilterSet):
    hubs_id__in = filters.Filter(field_name='hubs', lookup_expr='in')
    authors_id__in = filters.Filter(field_name='authors', lookup_expr='in')
    author_uploaded_by = filters.Filter(
        field_name='uploaded_by__author_profile',
        method='uploaded_by_author'
    )

    class Meta:
        model = Paper
        # TODO: Handle filtering on raw_authors in another way
        exclude = [
            'alternate_ids',
            'file',
            'csl_item',
            'oa_pdf_location',
            'raw_authors',
            'external_metadata',
            'pdf_file_extract',
            'edited_file_extract'
        ]

    def uploaded_by_author(self, queryset, name, value):
        filters = {
            name: value
        }
        qs = queryset.filter(**filters)
        return qs
