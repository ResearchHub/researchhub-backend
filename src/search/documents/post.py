from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from .base import BaseDocument

from search.analyzers import (
    title_analyzer,
    content_analyzer
)


@registry.register_document
class PostDocument(BaseDocument):
    auto_refresh = True

    hubs_flat = es_fields.TextField(attr='hubs_indexing_flat')
    hot_score = es_fields.IntegerField(attr='hot_score')
    score = es_fields.IntegerField(attr='score')
    discussion_count = es_fields.IntegerField(attr='discussion_count')
    unified_document_id = es_fields.IntegerField(attr='unified_document_id')
    title = es_fields.TextField(analyzer=title_analyzer)
    created_date = es_fields.DateField(attr='created_date')
    updated_date = es_fields.DateField(attr='updated_date')
    preview_img = es_fields.TextField(attr='preview_img')
    slug = es_fields.TextField(attr='slug')
    renderable_text = es_fields.TextField(attr='renderable_text', analyzer=content_analyzer)
    created_by_id = es_fields.IntegerField(attr='created_by_id')
    hubs = es_fields.ObjectField(
        attr='hubs_indexing',
        properties={
            'hub_image': es_fields.TextField(),
            'id': es_fields.IntegerField(),
            'is_locked': es_fields.TextField(),
            'is_removed': es_fields.TextField(),
            'name': es_fields.KeywordField(),
            'slug': es_fields.TextField(),
        }
    )


    class Index:
        name = 'post'

    class Django:
        model = ResearchhubPost
        queryset_pagination = 250
        fields = [
            'id',
            'document_type',
        ]


    def should_remove_from_index(self, obj):
        if obj.is_removed:
            return True

        return False
