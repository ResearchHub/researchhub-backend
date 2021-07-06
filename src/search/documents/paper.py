from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry
from django.db import models

from paper.models import Paper
from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)
from search.analyzers import (
    title_analyzer,
    name_analyzer,
    content_analyzer
)

from elasticsearch_dsl import Q
import utils.sentry as sentry

@registry.register_document
class PaperDocument(Document):
    hubs_flat = es_fields.TextField(attr='hubs_indexing_flat')
    discussion_count = es_fields.IntegerField(attr='discussion_count_indexing')
    score = es_fields.IntegerField(attr='score_indexing')
    hot_score = es_fields.IntegerField(attr='hot_score_indexing')
    summary = es_fields.TextField(attr='summary_indexing')
    title = es_fields.TextField(analyzer=title_analyzer)
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    paper_publish_date = es_fields.DateField(attr='paper_publish_date', format='yyyy-MM-dd')
    abstract = es_fields.TextField(attr='abstract_indexing', analyzer=content_analyzer)
    doi = es_fields.TextField(attr='doi_indexing', analyzer='keyword')
    authors = es_fields.TextField(attr='authors_indexing', analyzer=name_analyzer)
    raw_authors = es_fields.ObjectField(
        attr='raw_authors_indexing',
        properties={
            'first_name': es_fields.TextField(),
            'last_name': es_fields.TextField(),
            'full_name': es_fields.TextField(),
        }
    )
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

    auto_refresh = True


    class Index:
        name = 'paper'

    class Django:
        model = Paper
        fields = [
            'id'
        ]

    def update(self, thing, refresh=None, action='index', parallel=False, **kwargs):

        if refresh is not None:
            kwargs['refresh'] = refresh
        elif self.django.auto_refresh:
            kwargs['refresh'] = self.django.auto_refresh

        if isinstance(thing, models.Model):
            object_list = [thing]
        else:
            object_list = thing


        objects_to_remove = []
        objects_to_index = []
        for obj in object_list:
            if obj.is_removed:
                objects_to_remove.append(obj)
            else:
                objects_to_index.append(obj)

        try:
            self._bulk(
                self._get_actions(objects_to_index, action='index'),
                parallel=parallel,
                **kwargs
            )
            self._bulk(
                self._get_actions(objects_to_remove, action='delete'),
                parallel=parallel,
                **kwargs
            )
        except ConnectionError as e:
            sentry.log_info(e)
        except Exception as e:
            # This scenario is the result of removing objects
            # that do not exist in elastic search - 404s
            pass
