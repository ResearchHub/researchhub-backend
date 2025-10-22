import logging
from typing import override

from django.db.models import Q, QuerySet
from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry

from search.analyzers import content_analyzer
from user.models import Author

from .base import BaseDocument

logger = logging.getLogger(__name__)


@registry.register_document
class PersonDocument(BaseDocument):
    profile_image = es_fields.TextField(attr="profile_image_indexing")
    user_reputation = es_fields.IntegerField(attr="user_reputation_indexing")
    author_score = es_fields.IntegerField(attr="author_score")
    description = es_fields.TextField(attr="description", analyzer=content_analyzer)
    full_name = es_fields.TextField(attr="full_name", analyzer=content_analyzer)
    person_types = es_fields.KeywordField(attr="person_types_indexing")
    headline = es_fields.ObjectField(
        properties={
            "title": es_fields.TextField(),
        },
    )
    institutions = es_fields.ObjectField(
        attr="institutions_indexing",
        properties={
            "id": es_fields.IntegerField(),
            "name": es_fields.TextField(),
        },
    )
    suggestion_phrases = es_fields.CompletionField()
    user_id = es_fields.IntegerField(attr="user_id")
    reputation_hubs = es_fields.KeywordField()
    education = es_fields.KeywordField()
    created_date = es_fields.DateField(attr="created_date")

    class Index:
        name = "person"

    class Django:
        model = Author
        fields = [
            "id",
            "first_name",
            "last_name",
        ]

    @override
    def get_queryset(
        self,
        filter_: Q | None = None,
        exclude: Q | None = None,
        count: int = None,  # type: ignore[override]
    ) -> QuerySet:
        return (
            super()
            .get_queryset(filter_, exclude, count)
            .prefetch_related("institutions__institution")
        )

    def prepare_headline(self, instance) -> dict[str, str]:
        headline = instance.headline

        # Normalize headline to object format (mapping expects object with title field)
        if isinstance(headline, dict):
            # Already in object format: {"title": "...", "isPublic": true}
            # Ensure title field exists, add empty string if missing
            if "title" not in headline:
                headline = headline.copy()
                headline["title"] = ""
            return headline
        elif isinstance(headline, str):
            # Convert string to object format
            return {"title": headline}
        else:
            # Null or other type - use empty object
            return {"title": ""}

    def prepare_reputation_hubs(self, instance) -> list[str]:
        reputation_hubs = []
        if instance.reputation_list:
            for rep in instance.reputation_list:
                reputation_hubs.append(rep["hub"]["name"])

        return reputation_hubs

    def prepare_education(self, instance) -> list[str]:
        education = []
        if instance.education:
            for edu in instance.education:
                if edu and isinstance(edu, dict) and "name" in edu:
                    education.append(edu["name"])

        return education

    def prepare_suggestion_phrases(self, instance) -> list[dict[str, int]]:
        suggestions = []

        if instance.full_name:
            if instance.user:
                suggestions.append({"input": instance.full_name, "weight": 15})
            else:
                suggestions.append({"input": instance.full_name, "weight": 10})

        if instance.first_name:
            suggestions.append({"input": instance.first_name, "weight": 5})
        if instance.last_name:
            suggestions.append({"input": instance.last_name, "weight": 5})

        # Add institution names
        for author_institution in instance.institutions.all():
            if author_institution.institution.display_name:
                suggestions.append(
                    {"input": author_institution.institution.display_name, "weight": 3}
                )

                # Add full name + institution to account for people typing
                # name + institution
                suggestions.append(
                    {
                        "input": instance.first_name
                        + " "
                        + author_institution.institution.display_name,
                        "weight": 3,
                    }
                )

        return suggestions
