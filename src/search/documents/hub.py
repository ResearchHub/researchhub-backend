from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry
from django.db import models

from hub.models import Hub

# from search.analyzers import (

# )

import utils.sentry as sentry

@registry.register_document
class HubDocument(Document):
    paper_count = es_fields.IntegerField(attr='paper_count')
    subscriber_count = es_fields.IntegerField(attr='subscriber_count')
    discussion_count = es_fields.IntegerField(attr='discussion_count')

    class Index:
        name = 'hub'

    class Django:
        model = Hub
        fields = [
            'id',
            'name',
            'acronym',
            'hub_image',
            'is_locked',
        ]



    def should_remove_from_index(self, thing):
        return False


    """
    Overriding parent method to include an additional bulk
    operation for removing objects from elastic who are removed
    """
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
            if obj.is_removed or obj.is_locked:
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
