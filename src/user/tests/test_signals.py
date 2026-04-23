from django.test import TestCase

from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from researchhub_comment.tests.helpers import create_rh_comment
from user.models import User
from user.tests.helpers import create_random_default_user


class UserSignalsTests(TestCase):
    def setUp(self):
        self.paper_uploader = create_random_default_user("paper_uploader")
        self.paper = create_paper(uploaded_by=self.paper_uploader)

    def test_create_discussion_item_creates_action(self):
        user = create_random_default_user("rando")
        create_rh_comment(created_by=user, paper=self.paper)

        user.refresh_from_db()
        actions = user.actions.all()
        self.assertEqual(len(actions), 1)

    def test_create_thread_creates_action_with_paper_hubs(self):
        user = create_random_default_user("nacho")
        hub = create_hub(name="Nacho Libre")
        paper = create_paper(uploaded_by=user)
        paper.unified_document.hubs.add(hub)
        create_rh_comment(paper=paper, created_by=user)

        action = user.actions.all()[0]
        self.assertIn(hub, action.hubs.all())

    def test_new_user_is_auto_opted_into_staking(self):
        user = User.objects.create_user(
            username="staker@example.com",
            email="staker@example.com",
        )
        user.refresh_from_db()
        self.assertTrue(user.is_staking_opted_in)
        self.assertIsNotNone(user.staking_opted_in_date)
