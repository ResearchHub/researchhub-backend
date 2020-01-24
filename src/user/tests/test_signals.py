from django.test import TestCase

from discussion.tests.helpers import create_comment, create_thread
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from summary.models import Summary
from summary.tests.helpers import create_summary
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

    def test_create_summary_creates_action(self):
        user = create_random_default_user('summary_proposer')
        paper = create_paper()
        create_summary('proposed_summary', user, paper.id)

        user.refresh_from_db()
        actions = user.actions.all()
        self.assertEqual(len(actions), 1)

        action_item = actions[0].item
        self.assertTrue(isinstance(action_item, Summary))

    def test_create_thread_creates_action_with_paper_hubs(self):
        user = create_random_default_user('nacho')
        hub = create_hub(name='Nacho Libre')
        paper = create_paper()
        paper.hubs.add(hub)
        create_thread(paper=paper, created_by=user)

        action = user.actions.all()[0]
        self.assertIn(hub, action.hubs.all())
