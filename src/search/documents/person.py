import logging
from typing import override

from django.db.models import Q, QuerySet
from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry

from search.analyzers import content_analyzer
from user.models import Author, User

from .base import BaseDocument

logger = logging.getLogger(__name__)


@registry.register_document
class PersonDocument(BaseDocument):
    profile_image = es_fields.TextField(attr="profile_image_indexing")
    user_reputation = es_fields.IntegerField()
    author_score = es_fields.IntegerField(attr="author_score")
    description = es_fields.TextField(attr="description", analyzer=content_analyzer)
    full_name = es_fields.TextField(attr="full_name", analyzer=content_analyzer)
    person_types = es_fields.KeywordField()
    headline = es_fields.TextField(attr="headline", analyzer=content_analyzer)
    institutions = es_fields.ObjectField(
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
        # Update index when related User model is updated
        related_models = [User]
        # Reduce batch size to avoid circuit breaker exceptions during bulk indexing
        # Default is 1024, but person documents with institutions/education can be large
        queryset_pagination = 256

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

    def prepare_person_types(self, instance) -> list[str]:
        person_types = ["author"]
        if instance.user is not None:
            person_types.append("user")

        return person_types

    def prepare_institutions(self, instance) -> list[dict] | None:
        if instance.institutions is not None:
            return [
                {
                    "id": author_institution.institution.id,
                    "name": author_institution.institution.display_name,
                }
                for author_institution in instance.institutions.all()
            ]
        return None

    def prepare_user_reputation(self, instance) -> int:
        if instance.user is not None:
            return instance.user.reputation
        return 0

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

    def get_instances_from_related(
        self,
        related_instance: User,
    ) -> list[Author]:
        """
        When a user changes, update the related author profile.
        """
        if isinstance(related_instance, User):
            if hasattr(related_instance, "author_profile"):
                return [related_instance.author_profile]
        return []
