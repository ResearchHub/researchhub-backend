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
        try:
            first_name = instance.author_profile.first_name
            last_name = instance.author_profile.last_name
            full_name = f"{first_name} {last_name}"
        except Exception:
            full_name = f"{instance.first_name} {instance.last_name}"

        weight = instance.reputation + (
            VERIFIED_USER_WEIGHT_BONUS if instance.is_verified else 0
        )

        # Normalizes text for search by removing accents/diacritics
        def _normalize_for_search(text):
            if not text:
                return ""
            return (
                unicodedata.normalize("NFD", text)
                .encode("ascii", "ignore")
                .decode("ascii")
                .lower()
            )

        normalized_name = _normalize_for_search(full_name)
        original_words = full_name.split()
        normalized_words = normalized_name.split()

        input_list = original_words + [full_name] + normalized_words + [normalized_name]

        if len(original_words) >= 2:
            input_list.extend(
                [
                    f"{original_words[0]} {original_words[-1]}",
                    f"{normalized_words[0]} {normalized_words[-1]}",
                ]
            )

        # Remove duplicates while preserving order
        unique_input_list = list(dict.fromkeys(input_list))

        # Cap input size for performance
        MAX_INPUT_SIZE = 10
        if len(unique_input_list) > MAX_INPUT_SIZE:
            full_names = [item for item in unique_input_list if len(item.split()) >= 2]
            partial_names = [
                item for item in unique_input_list if len(item.split()) == 1
            ]

            prioritized_list = full_names[:MAX_INPUT_SIZE]
            remaining_slots = MAX_INPUT_SIZE - len(prioritized_list)
            if remaining_slots > 0:
                prioritized_list.extend(partial_names[:remaining_slots])

            unique_input_list = prioritized_list

        return {"input": unique_input_list, "weight": weight}

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
