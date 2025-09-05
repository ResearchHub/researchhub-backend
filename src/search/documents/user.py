import logging

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

    def prepare_author_profile(self, instance):
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
    def prepare_full_name_suggest(self, instance):
        full_name_suggest = ""
        try:
            full_name_suggest = f"{instance.author_profile.first_name} {instance.author_profile.last_name}"
        except Exception:
            # Some legacy users don't have an author profile
            full_name_suggest = f"{instance.first_name} {instance.last_name}"

        weight = instance.reputation

        if instance.is_verified:
            weight += 500

        return {
            "input": full_name_suggest.split() + [full_name_suggest],
            "weight": weight,
        }

    def prepare_full_name(self, instance):
        try:
            return f"{instance.author_profile.first_name} {instance.author_profile.last_name}"
        except Exception:
            # Some legacy users don't have an author profile
            return f"{instance.first_name} {instance.last_name}"

    def prepare_is_verified(self, instance):
        """Prepare the is_verified field for Elasticsearch indexing"""
        return instance.is_verified
