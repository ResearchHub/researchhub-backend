from django.db import models
from django_opensearch_dsl import Document
from django_opensearch_dsl.apps import DODConfig

import utils.sentry as sentry


class BaseDocument(Document):

    def update(self, thing, action, *args, refresh=None, using=None, **kwargs):
        """
        Overriding parent method to include an additional bulk
        operation for removing objects from the index that are soft-deleted.

        See: https://github.com/Codoc-os/django-opensearch-dsl/blob/e6cead9123ff9b67390c438876ca1ee313749cff/django_opensearch_dsl/documents.py#L238C9-L238C80
        """

        if refresh is None:
            refresh = getattr(
                self.Index, "auto_refresh", DODConfig.auto_refresh_enabled()
            )

        if isinstance(thing, models.Model):
            object_list = [thing]
        else:
            object_list = thing

        objects_to_remove = []
        objects_to_index = []
        for obj in object_list:
            if not self.should_index_object(obj):
                objects_to_remove.append(obj)
            else:
                objects_to_index.append(obj)

        try:
            index_result = self._bulk(
                self._get_actions(objects_to_index, action="index"),
                *args,
                refresh=refresh,
                using=using,
                **kwargs,
            )
            delete_result = self._bulk(
                self._get_actions(objects_to_remove, action="delete"),
                *args,
                refresh=refresh,
                using=using,
                **kwargs,
            )
            return (
                index_result[0] + delete_result[0],
                index_result[1] + delete_result[1],
            )
        except ConnectionError as e:
            sentry.log_info(e)
            return (0, 0)
        except Exception:
            # The likely scenario is the result of removing objects
            # that do not exist in elastic search - 404s
            return (0, 0)
