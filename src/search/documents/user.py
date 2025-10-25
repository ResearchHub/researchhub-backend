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

        # Build input list with priority order
        inputs, seen = [], set()

        def add_unique(value):
            if value and value not in seen:
                inputs.append(value)
                seen.add(value)

        # Add core names and combinations
        add_unique(full_name)
        first_parts = first.split() if first else []
        last_parts = last.split() if last else []

        if first_parts and last_parts:
            add_unique(f"{first_parts[0]} {last_parts[-1]}")
            norm_first = self._normalize_text(first_parts[0])
            norm_last = self._normalize_text(last_parts[-1])
            if norm_first and norm_last:
                add_unique(f"{norm_first} {norm_last}")

        add_unique(self._normalize_text(full_name))
        add_unique(first)
        add_unique(last)
        add_unique(self._normalize_text(first))
        add_unique(self._normalize_text(last))

        if first_parts:
            add_unique(first_parts[0])
        if last_parts:
            add_unique(last_parts[-1])

        # Add all individual name parts with their normalized versions for
        # comprehensive search coverage
        self._add_words_with_normalized(first_parts + last_parts, add_unique)

        weight = instance.reputation + (
            VERIFIED_USER_WEIGHT_BONUS if instance.is_verified else 0
        )
        return {"input": inputs[:MAX_INPUTS], "weight": weight}

    def _add_words_with_normalized(self, words, add_unique):
        """Add words and their normalized versions, avoiding duplicates"""
        for word in words:
            if word.strip():
                add_unique(word)
                normalized = self._normalize_text(word)
                if normalized and normalized != word.lower():
                    add_unique(normalized)

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
