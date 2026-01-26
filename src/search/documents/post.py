import logging
from typing import Any, override

from django.contrib.contenttypes.models import ContentType
from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry

from feed.models import FeedEntry
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from search.analyzers import content_analyzer, title_analyzer
from search.base.utils import generate_ngrams

from .base import BaseDocument

logger = logging.getLogger(__name__)


@registry.register_document
class PostDocument(BaseDocument):
    auto_refresh = True
    hubs_flat = es_fields.TextField()
    hot_score_v2 = es_fields.IntegerField()
    score = es_fields.IntegerField(attr="score")
    unified_document_id = es_fields.IntegerField(attr="unified_document_id")
    created_date = es_fields.DateField(attr="created_date")
    updated_date = es_fields.DateField(attr="updated_date")
    preview_img = es_fields.TextField(attr="preview_img")
    renderable_text = es_fields.TextField(
        attr="renderable_text", analyzer=content_analyzer
    )
    created_by_id = es_fields.IntegerField(attr="created_by_id")
    authors = es_fields.ObjectField(
        properties={
            "first_name": es_fields.TextField(),
            "last_name": es_fields.TextField(),
            "full_name": es_fields.TextField(),
        },
    )
    hubs = es_fields.ObjectField(
        properties={
            "id": es_fields.IntegerField(),
            "name": es_fields.KeywordField(),
            "slug": es_fields.TextField(),
        },
    )
    suggestion_phrases = es_fields.CompletionField()
    title = es_fields.TextField(
        analyzer=title_analyzer,
    )
    slug = es_fields.TextField()

    def prepare_authors(self, instance):
        return [
            {
                "first_name": author.first_name,
                "last_name": author.last_name,
                "full_name": author.full_name,
            }
            for author in instance.authors.all()
        ]

    def prepare_hubs(self, instance) -> list[dict[str, Any]]:
        """Prepare hubs data for indexing."""
        return [
            {
                "id": hub.id,
                "name": hub.name,
                "slug": hub.slug,
            }
            for hub in instance.hubs.all()
        ]

    def prepare_hubs_flat(self, instance) -> list[str]:
        """Prepare flat list of hub names for indexing."""
        return [hub.name for hub in instance.hubs.all()]

    def prepare_hot_score_v2(self, instance) -> int:
        try:
            post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
            feed_entry = FeedEntry.objects.filter(
                content_type=post_content_type,
                object_id=instance.id,
            ).first()
            if feed_entry:
                return feed_entry.hot_score_v2
        except Exception:
            pass
        return 0

    class Index:
        name = "post"

    class Django:
        model = ResearchhubPost
        fields = [
            "id",
            "document_type",
        ]
        # Update index when related unified document model is updated
        related_models = [ResearchhubUnifiedDocument]

    # Used specifically for "autocomplete" style suggest feature.
    # Inlcudes a bunch of phrases the user may search by.
    def prepare_suggestion_phrases(self, instance) -> list[dict[str, Any]]:
        hot_score_v2 = self.prepare_hot_score_v2(instance)
        weighted_inputs = []

        if instance.title:
            weighted_inputs.append(
                {
                    "input": instance.title,
                    "weight": self.calculate_phrase_weight(hot_score_v2, self.TITLE_WEIGHT),
                }
            )

            title_words = instance.title.split()
            for word in title_words:
                weighted_inputs.append(
                    {
                        "input": word,
                        "weight": self.calculate_phrase_weight(hot_score_v2, self.TITLE_WORDS_WEIGHT),
                    }
                )

            bigrams = generate_ngrams(title_words, n=2)
            for bigram in bigrams:
                weighted_inputs.append(
                    {
                        "input": bigram,
                        "weight": self.calculate_phrase_weight(hot_score_v2, self.BIGRAM_WEIGHT),
                    }
                )

        if instance.doi:
            weighted_inputs.append(
                {
                    "input": instance.doi,
                    "weight": self.calculate_phrase_weight(hot_score_v2, self.DOI_WEIGHT),
                }
            )

        try:
            author_names_only = [
                author.full_name
                for author in instance.authors.all()
                if author.first_name and author.last_name
            ]
            if author_names_only:
                all_authors_as_str = ", ".join(author_names_only)
                weighted_inputs.append(
                    {
                        "input": all_authors_as_str,
                        "weight": self.calculate_phrase_weight(hot_score_v2, self.AUTHOR_WEIGHT),
                    }
                )
                for author_name in author_names_only:
                    weighted_inputs.append(
                        {
                            "input": author_name,
                            "weight": self.calculate_phrase_weight(hot_score_v2, self.AUTHOR_WEIGHT),
                        }
                    )

            created_by = instance.created_by.full_name()
            weighted_inputs.append(
                {
                    "input": created_by,
                    "weight": self.calculate_phrase_weight(hot_score_v2, self.AUTHOR_WEIGHT),
                }
            )
        except Exception:
            pass

        seen = {}
        for item in weighted_inputs:
            input_str = item["input"]
            if input_str not in seen or item["weight"] > seen[input_str]["weight"]:
                seen[input_str] = item

        return list(seen.values())

    def get_instances_from_related(
        self,
        related_instance: ResearchhubUnifiedDocument,
    ) -> list[ResearchhubPost]:
        """
        When a unified document changes, update all related posts.
        """
        if isinstance(related_instance, ResearchhubUnifiedDocument):
            return list(related_instance.posts.all())
        return []

    @override
    def should_index_object(self, obj) -> bool:  # type: ignore[override]
        return not obj.is_removed
