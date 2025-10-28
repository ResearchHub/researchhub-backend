import logging
import math
import re
from typing import Any, override

from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry

from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from search.analyzers import content_analyzer, title_analyzer

from .base import BaseDocument

logger = logging.getLogger(__name__)


@registry.register_document
class PostDocument(BaseDocument):
    auto_refresh = True
    hubs_flat = es_fields.TextField(attr="hubs_indexing_flat")
    hot_score = es_fields.IntegerField(attr="hot_score")
    score = es_fields.IntegerField(attr="score")
    discussion_count = es_fields.IntegerField(attr="discussion_count")
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
        attr="hubs_indexing",
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
    def prepare_suggestion_phrases(self, instance) -> dict[str, Any]:
        phrases = []

        # Variation of title which may be searched by users
        if instance.title:
            phrases.append(instance.title)
            phrases.extend(instance.title.split())

            # For grant posts, add title without "Request For Proposals" prefix
            if instance.document_type == GRANT:
                stripped_title = self._strip_rfp_prefix(instance.title)
                if stripped_title and stripped_title != instance.title:
                    phrases.append(stripped_title)
                    phrases.extend(stripped_title.split())

        if instance.doi:
            phrases.append(instance.doi)

        # Variation of author names which may be searched by users
        try:
            author_names_only = [
                author.full_name
                for author in instance.authors.all()
                if author.first_name and author.last_name
            ]
            all_authors_as_str = ", ".join(author_names_only)
            created_by = instance.created_by.full_name()

            phrases.append(all_authors_as_str)
            phrases.append(created_by)
            phrases.extend(author_names_only)
        except Exception:
            pass

        # Assign weight based on how "hot" the post is
        weight = 1
        if instance.unified_document.hot_score > 0:
            # Scale down the hot score from 1 - 100 to avoid a huge range
            # of values that could result in bad suggestions
            weight = int(math.log(instance.unified_document.hot_score, 10) * 10)

        return {
            "input": list(set(phrases)),  # Dedupe using set
            "weight": weight,
        }

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

    def _strip_rfp_prefix(self, title: str) -> str:
        """
        Strip common "Request For Proposals" prefixes from grant titles.
        Returns the stripped title or original title if no prefix found.
        """
        if not title:
            return title

        # Common RFP prefix patterns (case-insensitive matching applied below)
        # Handles variations like:
        # - "Request For Proposals:", "request for proposals:", etc.
        # - "Request For Proposals -", "REQUEST FOR PROPOSALS -", etc.
        # - "RFP:", "rfp:", etc.
        rfp_patterns = [
            r"^Request\s+for\s+Proposals\s*[:-]?\s*",
            r"^RFP\s*[:-]?\s*",
        ]

        for pattern in rfp_patterns:
            stripped = re.sub(pattern, "", title, flags=re.IGNORECASE)
            if stripped != title:
                return stripped.strip()

        return title

    @override
    def should_index_object(self, obj) -> bool:  # type: ignore[override]
        return not obj.is_removed
