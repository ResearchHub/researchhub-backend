import json
from typing import Any

from django_opensearch_dsl import fields
from django_opensearch_dsl.registries import registry

from feed.models import FeedEntry
from search.documents.base import BaseDocument


@registry.register_document
class FeedEntryDocument(BaseDocument):
    id = fields.IntegerField(attr="id")
    content_type = fields.ObjectField(
        properties={
            "id": fields.IntegerField(attr="id"),
            "model": fields.TextField(attr="model"),
        }
    )
    object_id = fields.IntegerField()
    content = fields.ObjectField(
        properties={
            # Store problematic fields as JSON strings to avoid schema conflicts
            "comment_content_json": fields.TextField(),
            "parent_comment": fields.ObjectField(
                properties={
                    "comment_content_json": fields.TextField(),
                }
            ),
        },
    )
    hot_score = fields.IntegerField()
    metrics = fields.ObjectField(
        properties={
            "review_metrics": fields.ObjectField(
                properties={
                    "avg": fields.FloatField(),
                }
            ),
        }
    )
    action = fields.KeywordField()
    action_date = fields.DateField()
    created_date = fields.DateField()
    updated_date = fields.DateField()
    author = fields.ObjectField(
        properties={
            "id": fields.IntegerField(),
            "first_name": fields.TextField(),
            "last_name": fields.TextField(),
            "profile_image": fields.TextField(),
            "headline": fields.TextField(),
            "user": fields.ObjectField(
                properties={
                    "id": fields.IntegerField(),
                    "first_name": fields.TextField(),
                    "last_name": fields.TextField(),
                    "email": fields.TextField(),
                    "is_verified": fields.BooleanField(),
                }
            ),
        }
    )
    unified_document = fields.ObjectField(properties={})
    hubs = fields.NestedField(
        properties={
            "id": fields.IntegerField(),
            "name": fields.TextField(),
            "slug": fields.TextField(),
        }
    )

    class Index:
        name = "feed_entries"

    class Django:
        model = FeedEntry

    def prepare_hubs(self, instance) -> list[dict[str, Any]]:
        if instance.hubs.exists():
            return [
                {
                    "id": hub.id,
                    "name": hub.name,
                    "slug": hub.slug,
                }
                for hub in instance.hubs.all()
            ]
        return []

    def prepare_unified_document(self, instance) -> dict[str, Any] | None:
        if instance.unified_document:
            return {
                "id": instance.unified_document.id,
                "document_type": instance.unified_document.document_type,
            }
        return None

    def prepare_author(self, instance) -> dict[str, Any] | None:
        if instance.user and hasattr(instance.user, "author_profile"):
            profile = instance.user.author_profile

            return {
                "id": profile.id,
                "first_name": profile.first_name,
                "last_name": profile.last_name,
                "profile_image": (
                    profile.profile_image.url
                    if profile.profile_image and profile.profile_image.name
                    else None
                ),
                "headline": (
                    profile.headline.get("title")
                    if isinstance(profile.headline, dict)
                    else profile.headline
                ),
                "user": {
                    "id": instance.user.id,
                    "first_name": instance.user.first_name,
                    "last_name": instance.user.last_name,
                    "email": instance.user.email,
                    "is_verified": instance.user.is_verified,
                },
            }
        return None

    def prepare_content(self, instance):
        if not instance.content:
            return None

        content_copy = dict(instance.content)
        return self._serialize_json_fields(content_copy)

    def _serialize_json_fields(self, data, json_field_names=None):
        """
        Recursively convert specified fields to JSON strings in nested structures.
        """
        if json_field_names is None:
            json_field_names = ["comment_content_json"]

        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if key in json_field_names and not isinstance(value, str):
                    # Convert to JSON string
                    result[key] = json.dumps(value)
                elif isinstance(value, (dict, list)):
                    # Recursively process nested structures
                    result[key] = self._serialize_json_fields(value, json_field_names)
                else:
                    result[key] = value
            return result
        elif isinstance(data, list):
            return [
                self._serialize_json_fields(item, json_field_names) for item in data
            ]
        else:
            return data
