import logging

from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, token_filter

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
    full_name_suggest = es_fields.Completion()
    full_name = es_fields.TextField(
        analyzer=edge_ngram_analyzer,
        search_analyzer="standard",
    )
    created_date = es_fields.DateField()

    author_profile = es_fields.ObjectField(
        properties={
            "profile_img": es_fields.TextField(),
            "id": es_fields.IntegerField(),
        },
    )

    class Index:
        name = "user"

    # Let ES know which fields we want indexed
    class Django:
        model = User
        queryset_pagination = 250
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
            logger.warn(f"Failed to prepare author profile for user {instance.id}: {e}")
            return None

        try:
            profile["profile_image"] = instance.author_profile.profile_image.url
        except Exception as e:
            logger.warn(f"Failed to prepare profile image for user {instance.id}: {e}")

        return profile

    # Used specifically for "autocomplete" style suggest feature
    def prepare_full_name_suggest(self, instance):
        full_name_suggest = ""
        try:
            full_name_suggest = f"{instance.author_profile.first_name} {instance.author_profile.last_name}"
        except Exception:
            # Some legacy users don't have an author profile
            full_name_suggest = f"{instance.first_name} {instance.last_name}"

        return {
            "input": full_name_suggest.split() + [full_name_suggest],
            "weight": instance.reputation,
        }

    def prepare_full_name(self, instance):
        try:
            return f"{instance.author_profile.first_name} {instance.author_profile.last_name}"
        except Exception:
            # Some legacy users don't have an author profile
            return f"{instance.first_name} {instance.last_name}"

    def prepare(self, instance):
        try:
            data = super().prepare(instance)
        except Exception as e:
            logger.error(f"Failed to prepare data for user {instance.id}: {e}")
            return None

        try:
            data["full_name_suggest"] = self.prepare_full_name_suggest(instance)
        except Exception as e:
            logger.warn(
                f"Failed to prepare full name suggest for user {instance.id}: {e}"
            )
            data["full_name_suggest"] = []

        return data
