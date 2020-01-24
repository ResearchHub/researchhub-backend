from django.test import TestCase

from user.tasks import get_latest_actions
from user.tests.helpers import create_actions


class UserTasksTests(TestCase):
    def setUp(self):
        pass

    def test_get_lastest_actions(self):
        first_action = create_actions(1)
        create_actions(9)
        last_cursor = 1

        latest_actions, next_cursor = get_latest_actions(last_cursor)

        self.assertEqual(len(latest_actions), 9)
        self.assertFalse(first_action in latest_actions)

        latest_actions, next_cursor = get_latest_actions(next_cursor)

        self.assertEqual(len(latest_actions), 0)

        latest_actions, next_cursor = get_latest_actions(3)

        self.assertEqual(len(latest_actions), 7)
        self.assertFalse(first_action in latest_actions)
