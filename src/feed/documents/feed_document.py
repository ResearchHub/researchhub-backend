import copy
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
    content = fields.ObjectField(properties={})
    hot_score = fields.IntegerField()
    metrics = fields.ObjectField(properties={})
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

            # Need to safely check if userverification exists since we don't have
            # a corresponding field or property in the user model yet.
            # The existing `is_verified` field is the old verification status.
            uv = getattr(instance.user, "userverification", None)
            is_verified = uv.is_verified if uv and hasattr(uv, "is_verified") else False

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
                    "is_verified": is_verified,
                },
            }
        return None

    def prepare_content(self, instance):
        # Deep copy and sanitize dict inserts in comment_content_json.ops
        content = instance.content or {}
        content_copy = copy.deepcopy(content)

        def sanitize(obj):
            if isinstance(obj, dict):
                # if this dict contains Quill ops element, sanitize inserts
                ccj = obj.get("comment_content_json")
                if isinstance(ccj, dict) and isinstance(ccj.get("ops"), list):
                    for op in ccj["ops"]:
                        ins = op.get("insert")
                        if isinstance(ins, dict):
                            op["insert"] = json.dumps(ins)
                # recurse into nested values
                for v in obj.values():
                    sanitize(v)
            elif isinstance(obj, list):
                for item in obj:
                    sanitize(item)

        sanitize(content_copy)
        return content_copy
