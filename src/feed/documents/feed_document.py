import json

from django_elasticsearch_dsl import Document, fields
from django_elasticsearch_dsl.registries import registry

from feed.models import FeedEntry


@registry.register_document
class FeedEntryDocument(Document):
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
            "parent_comment": fields.TextField(),
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

    def prepare_hubs(self, instance):
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

    def prepare_unified_document(self, instance):
        if instance.unified_document:
            return {
                "id": instance.unified_document.id,
                "document_type": instance.unified_document.document_type,
            }
        return None

    def prepare_author(self, instance):
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
                    "is_verified": instance.user.is_verified_v2,
                },
            }
        return None

    def prepare_content(self, instance):
        if not instance.content:
            return None

        content_copy = dict(instance.content)

        if content_copy:
            # Convert problematic fields to JSON strings to avoid schema conflicts
            # Only convert to JSON if they're not already strings
            if "comment_content_json" in content_copy:
                if not isinstance(content_copy["comment_content_json"], str):
                    content_copy["comment_content_json"] = json.dumps(
                        content_copy["comment_content_json"]
                    )

            if "parent_comment" in content_copy:
                if not isinstance(content_copy["parent_comment"], str):
                    content_copy["parent_comment"] = json.dumps(
                        content_copy["parent_comment"]
                    )

            return content_copy
