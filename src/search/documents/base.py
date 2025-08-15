from django.db import models
from django_opensearch_dsl import Document


class BaseDocument(Document):

    def update(self, thing, action, *args, refresh=None, using=None, **kwargs):
        """
        Override to handle soft deletes by removing documents from index
        when should_index_object returns False.

        See: https://github.com/Codoc-os/django-opensearch-dsl/blob/e6cead9123ff9b67390c438876ca1ee313749cff/django_opensearch_dsl/documents.py#L238C9-L238C80
        """
        if isinstance(thing, models.Model):
            object_list = [thing]
        else:
            object_list = thing

        # AWS OpenSearch has instance-type based limits for the size of HTTP payloads.
        # See: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/limits.html#network-limits
        # Set max_chunk_bytes to 8MB to safely stay under the 10MB limit
        kwargs.setdefault("max_chunk_bytes", 8 * 1024 * 1024)  # 8MB

        # Split objects based on whether they should be indexed
        to_index = []
        to_delete = []
        for obj in object_list:
            if self.should_index_object(obj):
                to_index.append(obj)
            else:
                to_delete.append(obj)

        # Process both operations and combine results
        total_success = 0
        total_errors = []

        if to_index:
            success, errors = super().update(
                to_index, "index", *args, refresh=refresh, using=using, **kwargs
            )
            total_success += success
            total_errors.extend(errors)

        if to_delete:
            success, errors = super().update(
                to_delete, "delete", *args, refresh=refresh, using=using, **kwargs
            )
            total_success += success
            total_errors.extend(errors)

        return (total_success, total_errors)
