import logging
import unicodedata
from typing import Any, override

from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry
from opensearchpy import analyzer, token_filter

from user.models import User

from .base import BaseDocument

logger = logging.getLogger(__name__)

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


@registry.register_document
class UserDocument(BaseDocument):
    auto_refresh = True
    profile_img = es_fields.TextField()
    full_name_suggest = es_fields.CompletionField()
    full_name = es_fields.TextField(
        analyzer=edge_ngram_analyzer,
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
        full_name_suggest = ""
        try:
            full_name_suggest = (
                f"{instance.author_profile.first_name} "
                f"{instance.author_profile.last_name}"
            )
        except Exception:
            # Some legacy users don't have an author profile
            full_name_suggest = f"{instance.first_name} {instance.last_name}"

        weight = instance.reputation

        if instance.is_verified:
            weight += 500

        # Create ASCII-normalized version for better search matching
        def normalize_for_search(text):
            """Normalize text by removing accents for better search matching.

            This function converts accented characters to their ASCII equivalents,
            enabling searches like 'martin' to match 'Martín'.
            """
            if not text:
                return ""
            return (
                unicodedata.normalize("NFD", text)
                .encode("ascii", "ignore")
                .decode("ascii")
                .lower()
            )

        normalized_name = normalize_for_search(full_name_suggest)

        # Include both original and normalized versions in the input
        # Also include partial combinations for better matching
        original_words = full_name_suggest.split()
        normalized_words = normalized_name.split()

        input_list = (
            original_words  # Original words with accents
            + [full_name_suggest]  # Original full name
            + normalized_words  # Normalized words without accents
            + [normalized_name]  # Normalized full name
        )

        # Add partial combinations for better matching
        # (e.g., "martin rivero" from "martin nicolas rivero")
        if len(original_words) >= 2:
            # Add first + last name combinations
            first_last_original = f"{original_words[0]} {original_words[-1]}"
            first_last_normalized = f"{normalized_words[0]} {normalized_words[-1]}"
            input_list.append(first_last_original)  # "Martín Rivero"
            input_list.append(first_last_normalized)  # "martin rivero"

        # Remove duplicates while preserving order
        seen = set()
        unique_input_list = []
        for item in input_list:
            if item not in seen:
                seen.add(item)
                unique_input_list.append(item)

        return {
            "input": unique_input_list,
            "weight": weight,
        }

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
