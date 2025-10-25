import logging
import unicodedata
from typing import Any, override

from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry
from opensearchpy import analyzer, token_filter

from user.models import User

from .base import BaseDocument

logger = logging.getLogger(__name__)

# Weight bonus for verified users in search suggestions
VERIFIED_USER_WEIGHT_BONUS = 500

edge_ngram_filter = token_filter(
    "edge_ngram_filter",
    type="edge_ngram",
    min_gram=1,
    max_gram=20,
)

edge_ngram_analyzer = analyzer(
    "edge_ngram_analyzer",
    tokenizer="standard",
    filter=["lowercase", edge_ngram_filter],
)

name_analyzer = analyzer(
    "name_analyzer",
    tokenizer="standard",
    filter=[
        "lowercase",
        token_filter("asciifolding", type="asciifolding", preserve_original=True),
    ],
)


@registry.register_document
class UserDocument(BaseDocument):
    auto_refresh = True
    profile_img = es_fields.TextField()
    full_name_suggest = es_fields.CompletionField()
    full_name = es_fields.TextField(
        analyzer=name_analyzer,
        search_analyzer="standard",
    )
    created_date = es_fields.DateField()
    is_verified = es_fields.BooleanField()
    is_suspended = es_fields.BooleanField()

    author_profile = es_fields.ObjectField()

    class Index:
        name = "user"

    # Let ES know which fields we want indexed
    class Django:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "reputation",
        ]

    def prepare_author_profile(self, instance) -> dict[str, Any] | None:
        profile = None

        try:
            profile = {
                "id": instance.author_profile.id,
                "headline": instance.author_profile.headline,
            }
        except Exception as e:
            logger.warning(
                f"Failed to prepare author profile for user {instance.id}: {e}"
            )
            return None

        profile["profile_image"] = instance.author_profile.profile_image_indexing

        return profile

    # Used specifically for "autocomplete" style suggest feature
    def prepare_full_name_suggest(self, instance) -> dict[str, Any]:
        MAX_INPUTS = 10
        VERIFIED_USER_WEIGHT_BONUS = 500

        # Get names with fallback to user model
        try:
            first = (instance.author_profile.first_name or "").strip()
            last = (instance.author_profile.last_name or "").strip()
        except AttributeError:
            first = (instance.first_name or "").strip()
            last = (instance.last_name or "").strip()

        full_name = f"{first} {last}".strip()
        if not full_name:
            return {"input": [], "weight": 0}

        # Build input set with original and normalized versions
        inputs = {full_name, first, last}

        # Add normalized versions if they provide value
        normalized_full = self._normalize_text(full_name)
        if normalized_full:
            inputs.add(normalized_full)

        # Add individual normalized words
        normalized_first = self._normalize_text(first)
        normalized_last = self._normalize_text(last)
        if normalized_first:
            inputs.add(normalized_first)
        if normalized_last:
            inputs.add(normalized_last)

        # Add first+last combinations for better searchability
        if first and last:
            inputs.add(f"{first} {last}")
            normalized_first_last = f"{normalized_first} {normalized_last}"
            if normalized_first_last.strip():
                inputs.add(normalized_first_last)

        # Remove empty strings and limit size
        inputs.discard("")
        input_list = list(inputs)[:MAX_INPUTS]

        weight = instance.reputation + (
            VERIFIED_USER_WEIGHT_BONUS if instance.is_verified else 0
        )
        return {"input": input_list, "weight": weight}

    def _normalize_text(self, text: str) -> str:
        """Normalize text for search by removing accents/diacritics"""
        if not text:
            return ""
        return (
            unicodedata.normalize("NFD", text)
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
        )

    def prepare_full_name(self, instance) -> str:
        try:
            return (
                f"{instance.author_profile.first_name} "
                f"{instance.author_profile.last_name}"
            )
        except Exception:
            # Some legacy users don't have an author profile
            return f"{instance.first_name} {instance.last_name}"

    def prepare_is_verified(self, instance) -> bool:
        """Prepare the is_verified field for Elasticsearch indexing"""
        return instance.is_verified

    def prepare_is_suspended(self, instance) -> bool:
        """Prepare the is_suspended field for Elasticsearch indexing"""
        return instance.is_suspended

    @override
    def should_index_object(self, obj) -> bool:
        """Exclude suspended users from the index"""
        return not obj.is_suspended
