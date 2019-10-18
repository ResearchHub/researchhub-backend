from django.test import TestCase

from discussion.tests.test_helpers import create_comment, upvote_comment
from paper.test_helpers import create_paper
from user.test_helpers import create_random_default_user


class SignalTests(TestCase):

    def setUp(self):
        pass

    def test_create_paper_increases_rep_by_1(self):
        unique_value = 'Ronald Weasley'
        user = self.create_random_default_user(unique_value)
        create_paper(uploaded_by=user)
        self.assertEqual(user.reputation, 2)
