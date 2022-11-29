from django_filters import rest_framework as filters

from .models import Paper


class PaperFilter(filters.FilterSet):
    hubs_id__in = filters.Filter(field_name="hubs", lookup_expr="in")
    authors_id__in = filters.Filter(field_name="authors", lookup_expr="in")
    author_uploaded_by = filters.Filter(
        field_name="uploaded_by__author_profile", method="uploaded_by_author"
    )

    class Meta:
        model = Paper
        # TODO: Handle filtering on raw_authors in another way
        exclude = [
            "abstract_src",
            "alternate_ids",
            "csl_item",
            "edited_file_extract",
            "external_metadata",
            "file",
            "oa_pdf_location",
            "pdf_file_extract",
            "raw_authors",
        ]

    def uploaded_by_author(self, queryset, name, value):
        filters = {name: value}
        qs = queryset.filter(**filters)
        return qs
