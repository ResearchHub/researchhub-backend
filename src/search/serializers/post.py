from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from search.documents import PostDocument
from user.models import User
from user.serializers import UserSerializer


class PostDocumentSerializer(DocumentSerializer):

    created_by = serializers.SerializerMethodField()

    class Meta(object):
        document = PostDocument
        fields = [
            'id',
            'hubs_flat',
            'hot_score',
            'score',
            'discussion_count',
            'unified_document_id',
            'hubs',
            'created_date',
            'updated_date',
            'preview_img',
            'title',
            'renderable_text',
            'slug',
            'created_by_id',
        ]

    def get_created_by(self, obj):
        author = User.objects.get(
            id=obj.created_by_id
        )

        return UserSerializer(author, read_only=True).data
        
