from django.db import models
from django_opensearch_dsl import Document
from django_opensearch_dsl.apps import DODConfig


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

        # AWS OpenSearch has instance-type based limits for the size of HTTP payloads.
        # See: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/limits.html#network-limits
        # Set max_chunk_bytes to 8MB to safely stay under the 10MB limit
        bulk_kwargs = kwargs.copy()
        bulk_kwargs.setdefault("max_chunk_bytes", 8 * 1024 * 1024)  # 8MB

        index_result = self._bulk(
            self._get_actions(objects_to_index, action="index"),
            *args,
            refresh=refresh,
            using=using,
            **bulk_kwargs,
        )
        delete_result = self._bulk(
            self._get_actions(objects_to_remove, action="delete"),
            *args,
            refresh=refresh,
            using=using,
            **bulk_kwargs,
        )
        return (
            index_result[0] + delete_result[0],
            index_result[1] + delete_result[1],
        )
