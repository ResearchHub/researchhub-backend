from django.test import TestCase

from discussion.tests.test_helpers import create_comment, upvote_comment
from paper.test_helpers import create_paper
from user.test_helpers import create_random_default_user


class SignalTests(TestCase):

    def setUp(self):
        self.user = create_random_default_user('Molly')

    def test_create_paper_increases_rep_by_1(self):
        user = create_random_default_user('Ronald')
        create_paper(uploaded_by=user)
        self.assertEqual(user.reputation, 2)

    def test_comment_upvoted_increases_rep_by_5(self):
        user = create_random_default_user('Ginny')
        comment = create_comment(created_by=user)
        upvote_comment(comment=comment, created_by=self.user)
        self.assertEqual(user.reputation, 6)
