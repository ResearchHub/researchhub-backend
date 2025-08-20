from typing import override

from django_opensearch_dsl import Document


class BaseDocument(Document):

    @override
    def _get_actions(self, object_list, action):
        """
        Override the base `_get_actions` method to support soft-delete behavior.
        """
        for object_instance in object_list:
            if action == "delete" or self.should_index_object(object_instance):
                yield self._prepare_action(object_instance, action)
            else:
                # delete soft-deleted objects (`should_index_object` is False)
                yield self._prepare_action(object_instance, "delete")
