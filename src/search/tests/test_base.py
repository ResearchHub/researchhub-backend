import unittest
from unittest.mock import Mock, call

from search.documents.base import BaseDocument


class TestBaseDocument(unittest.TestCase):

    def setUp(self):
        self.document = BaseDocument()
        self.document._prepare_action = Mock(
            side_effect=lambda obj, action: {"object": obj, "action": action}
        )
        self.document.should_index_object = Mock()

    def test_get_actions_with_delete_action(self):
        """
        Test _get_actions when action is 'delete'.
        """
        # Arrange
        object_list = [Mock(id=1), Mock(id=2), Mock(id=3)]
        action = "delete"

        # Act
        results = list(self.document._get_actions(object_list, action))

        # Assert
        self.assertEqual(len(results), 3)
        for i, result in enumerate(results):
            self.assertEqual(result["object"], object_list[i])
            self.assertEqual(result["action"], "delete")

        # verify _prepare_action was called correctly
        expected_calls = [
            call(object_list[0], "delete"),
            call(object_list[1], "delete"),
            call(object_list[2], "delete"),
        ]
        self.document._prepare_action.assert_has_calls(expected_calls)

        # should_index_object should not be called when action is delete
        self.document.should_index_object.assert_not_called()

    def test_get_actions_with_index_action_all_indexable(self):
        """
        Test _get_actions when action is 'index' and all objects should be indexed.
        """
        # Arrange
        object_list = [Mock(id=1), Mock(id=2), Mock(id=3)]
        action = "index"
        self.document.should_index_object.return_value = True

        # Act
        results = list(self.document._get_actions(object_list, action))

        # Assert
        self.assertEqual(len(results), 3)
        for i, result in enumerate(results):
            self.assertEqual(result["object"], object_list[i])
            self.assertEqual(result["action"], "index")

        # verify should_index_object was called for each object
        self.assertEqual(self.document.should_index_object.call_count, 3)

        # verify _prepare_action was called with index action
        expected_calls = [
            call(object_list[0], "index"),
            call(object_list[1], "index"),
            call(object_list[2], "index"),
        ]
        self.document._prepare_action.assert_has_calls(expected_calls)

    def test_get_actions_with_index_action_none_indexable(self):
        """
        Test _get_actions when action is 'index' but no objects should be indexed.
        """
        # Arrange
        object_list = [Mock(id=1), Mock(id=2), Mock(id=3)]
        action = "index"
        self.document.should_index_object.return_value = False

        # Act
        results = list(self.document._get_actions(object_list, action))

        # Assert
        self.assertEqual(len(results), 3)
        for i, result in enumerate(results):
            self.assertEqual(result["object"], object_list[i])
            self.assertEqual(
                result["action"], "delete"
            )  # should delete non-indexable objects

        # verify should_index_object was called for each object
        self.assertEqual(self.document.should_index_object.call_count, 3)

        # verify _prepare_action was called with delete action for soft-deleted objects
        expected_calls = [
            call(object_list[0], "delete"),
            call(object_list[1], "delete"),
            call(object_list[2], "delete"),
        ]
        self.document._prepare_action.assert_has_calls(expected_calls)

    def test_get_actions_with_mixed_indexable_objects(self):
        """
        Test _get_actions with mixed indexable and non-indexable objects.
        """
        # Arrange
        object_list = [Mock(id=1), Mock(id=2), Mock(id=3)]
        action = "update"
        # mock should_index_object to return different values
        self.document.should_index_object.side_effect = [True, False, True]

        # Act
        results = list(self.document._get_actions(object_list, action))

        # Assert
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["action"], "update")  # first object is indexable
        self.assertEqual(
            results[1]["action"], "delete"
        )  # second object is not indexable
        self.assertEqual(results[2]["action"], "update")  # third object is indexable

        # verify _prepare_action was called correctly
        expected_calls = [
            call(object_list[0], "update"),
            call(object_list[1], "delete"),
            call(object_list[2], "update"),
        ]
        self.document._prepare_action.assert_has_calls(expected_calls)
