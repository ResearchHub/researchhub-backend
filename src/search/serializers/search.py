"""
Serializers for unified search results.
"""

from rest_framework import serializers


class UnifiedSearchRequestSerializer(serializers.Serializer):
    """Serializer for validating unified search request parameters."""

    q = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Search query string",
    )
    page = serializers.IntegerField(
        required=False,
        default=1,
        min_value=1,
        help_text="Page number",
    )
    page_size = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=100,
        help_text="Number of results per page (max 100)",
    )
    sort = serializers.ChoiceField(
        choices=["relevance", "newest"],
        required=False,
        default="relevance",
        help_text="Sort option",
    )


class AuthorSerializer(serializers.Serializer):
    """Serializer for author information in search results."""

    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    full_name = serializers.CharField()


class HubSerializer(serializers.Serializer):
    """Serializer for hub information in search results."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()


class InstitutionSerializer(serializers.Serializer):
    """Serializer for institution information in search results."""

    id = serializers.IntegerField()
    name = serializers.CharField()


class DocumentResultSerializer(serializers.Serializer):
    """Serializer for document (paper/post) search results."""

    id = serializers.IntegerField()
    type = serializers.CharField()
    title = serializers.CharField()
    snippet = serializers.CharField(allow_null=True, required=False)
    matched_field = serializers.CharField(allow_null=True, required=False)
    authors = AuthorSerializer(many=True, required=False)
    created_date = serializers.DateTimeField(allow_null=True, required=False)
    paper_publish_date = serializers.DateTimeField(allow_null=True, required=False)
    score = serializers.IntegerField(required=False)
    _search_score = serializers.FloatField(required=False)
    hubs = HubSerializer(many=True, required=False)
    unified_document_id = serializers.IntegerField(required=False)

    # Paper-specific fields
    doi = serializers.CharField(allow_null=True, required=False)
    citations = serializers.IntegerField(required=False)

    # Post-specific fields
    slug = serializers.CharField(allow_null=True, required=False)
    document_type = serializers.CharField(allow_null=True, required=False)


class PersonResultSerializer(serializers.Serializer):
    """Serializer for person (author/user) search results."""

    id = serializers.IntegerField()
    full_name = serializers.CharField()
    profile_image = serializers.CharField(allow_null=True, required=False)
    snippet = serializers.CharField(allow_null=True, required=False)
    matched_field = serializers.CharField(allow_null=True, required=False)
    headline = serializers.DictField(allow_null=True, required=False)
    institutions = InstitutionSerializer(many=True, required=False)
    user_reputation = serializers.IntegerField(required=False)
    user_id = serializers.IntegerField(allow_null=True, required=False)
    _search_score = serializers.FloatField(required=False)


class AggregationBucketSerializer(serializers.Serializer):
    """Serializer for aggregation buckets."""

    key = serializers.CharField()
    doc_count = serializers.IntegerField()


class SearchAggregationsSerializer(serializers.Serializer):
    """Serializer for search aggregations."""

    years = AggregationBucketSerializer(many=True, required=False)
    hubs = AggregationBucketSerializer(many=True, required=False)
    content_types = AggregationBucketSerializer(many=True, required=False)


class UnifiedSearchResultSerializer(serializers.Serializer):
    """Serializer for unified search results."""

    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    documents = DocumentResultSerializer(many=True)
    people = PersonResultSerializer(many=True)
    aggregations = SearchAggregationsSerializer(required=False)
