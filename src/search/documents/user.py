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

        # Build input list with original and normalized versions
        # Use a list to preserve priority order (most important first)
        inputs = []
        seen = set()

        def add_unique(value):
            if value and value not in seen:
                inputs.append(value)
                seen.add(value)

        # Highest priority: full name
        add_unique(full_name)

        # Add first+last combinations for better searchability (high priority)
        first_parts = first.split() if first else []
        last_parts = last.split() if last else []

        if first and last:
            # Add first part of first name + last part of last name (high priority)
            if first_parts and last_parts:
                first_last_combination = f"{first_parts[0]} {last_parts[-1]}"
                add_unique(first_last_combination)

                # Add normalized version of first+last combination
                normalized_first_part = self._normalize_text(first_parts[0])
                normalized_last_part = self._normalize_text(last_parts[-1])
                if normalized_first_part and normalized_last_part:
                    norm_combo = f"{normalized_first_part} {normalized_last_part}"
                    add_unique(norm_combo)

        # Add normalized full name
        normalized_full = self._normalize_text(full_name)
        add_unique(normalized_full)

        # Add first and last names
        add_unique(first)
        add_unique(last)

        # Add individual normalized words for first and last
        normalized_first = self._normalize_text(first)
        normalized_last = self._normalize_text(last)
        add_unique(normalized_first)
        add_unique(normalized_last)

        # Add individual words from first and last names (medium priority)
        # Prioritize first and last parts of the name
        if first_parts:
            add_unique(first_parts[0])  # First part of first name
        if last_parts:
            add_unique(last_parts[-1])  # Last part of last name

        # Add remaining individual words (lower priority)
        for word in first_parts:
            if word.strip():
                add_unique(word)
                normalized_word = self._normalize_text(word)
                if normalized_word and normalized_word != word.lower():
                    add_unique(normalized_word)
        for word in last_parts:
            if word.strip():
                add_unique(word)
                normalized_word = self._normalize_text(word)
                if normalized_word and normalized_word != word.lower():
                    add_unique(normalized_word)

        # Limit size
        input_list = inputs[:MAX_INPUTS]

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
