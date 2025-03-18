from django.db import models
from django_elasticsearch_dsl import Document

import utils.sentry as sentry


class BaseDocument(Document):

    """
    Override and add conditions for when object should be removed
    from index
    """
    def should_remove_from_index(self, obj):
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
            if self.should_remove_from_index(obj):
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
            # The likely scenario is the result of removing objects
            # that do not exist in elastic search - 404s
            pass