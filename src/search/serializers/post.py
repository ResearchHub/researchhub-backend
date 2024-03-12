from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from search.documents import PostDocument
from user.models import User
from user.serializers import UserSerializer
from utils import sentry


class PostDocumentSerializer(DocumentSerializer):
    created_by = serializers.SerializerMethodField()
    highlight = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()

    class Meta(object):
        document = PostDocument
        fields = [
            "id",
            "hubs_flat",
            "hot_score",
            "score",
            "discussion_count",
            "unified_document_id",
            "hubs",
            "created_date",
            "updated_date",
            "preview_img",
            "title",
            "renderable_text",
            "slug",
            "created_by_id",
        ]

    def get_highlight(self, obj):
        if hasattr(obj.meta, "highlight"):
            return obj.meta.highlight.__dict__["_d_"]
        return {}

    def get_slug(self, hit):
        slug = ""
        try:
            obj = ResearchhubPost.objects.get(id=hit["id"])
            slug = obj.slug
        except:
            pass

        return slug

    def get_created_by(self, obj):
        try:
            author = User.objects.get(id=obj.created_by_id)
            return UserSerializer(author, read_only=True).data
        except:
            # The object no longer exist in the DB
            pass
