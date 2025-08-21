import logging
from typing import override

from django_opensearch_dsl import Document

logger = logging.getLogger(__name__)


class BaseDocument(Document):

    @override
    def _get_actions(self, object_list, action):
        """
        Override the base `_get_actions` method to support soft-delete behavior.
        Additionally, any exceptions from the prepare_[field] methods will be
        logged without aborting the indexing process.
        """
        for object_instance in object_list:
            if action == "delete" or self.should_index_object(object_instance):
                # Execute `prepare` methods with graceful error handling to avoid
                # aborting the indexing process:
                try:
                    yield self._prepare_action(object_instance, action)
                except Exception as e:
                    logger.warning(
                        f"Failed to index {self.__class__.__name__} "
                        f"id={object_instance.id}: {e}"
                    )
                    continue
            else:
                # delete soft-deleted objects (`should_index_object` is False)
                yield self._prepare_action(object_instance, "delete")
