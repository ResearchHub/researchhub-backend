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
        processed = 0
        indexed = 0
        deleted = 0
        failed = 0

        for object_instance in object_list:
            processed += 1
            if action == "delete" or self.should_index_object(object_instance):
                # Execute `prepare` methods with graceful error handling to avoid
                # aborting the indexing process:
                try:
                    action_data = self._prepare_action(object_instance, action)
                    indexed += 1
                    logger.debug(
                        f"Prepared action for {self.__class__.__name__} "
                        f"id={object_instance.id}"
                    )
                    yield action_data
                except Exception as e:
                    failed += 1
                    logger.warning(
                        f"Failed to index {self.__class__.__name__} "
                        f"id={object_instance.id}: {e}"
                    )
                    continue
            else:
                # delete soft-deleted objects (`should_index_object` is False)
                deleted += 1
                logger.debug(
                    f"Deleting soft-deleted {self.__class__.__name__} "
                    f"id={object_instance.id}"
                )
                yield self._prepare_action(object_instance, "delete")

        logger.info(
            f"_get_actions summary for {self.__class__.__name__}: "
            f"processed={processed}, indexed={indexed}, deleted={deleted}, failed={failed}"
        )
