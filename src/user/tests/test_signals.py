from django.test import TestCase

from discussion.tests.helpers import create_comment
from user.tests.helpers import create_random_default_user


class UserSignalsTests(TestCase):

    def setUp(self):
        pass

    def test_create_discussion_item_creates_action(self):
        user = create_random_default_user('rando')
        create_comment(created_by=user)

        user.refresh_from_db()
        actions = user.actions.all()
        self.assertEqual(len(actions), 1)
