from django.test import TestCase

from discussion.tests.test_helpers import (
    create_comment,
    upvote_comment,
    downvote_comment,
    update_to_downvote
)
from paper.test_helpers import create_paper
from user.test_helpers import create_random_default_user


class SignalTests(TestCase):

    def setUp(self):
        self.user = create_random_default_user('Molly')
        self.recipient = create_random_default_user('Harry')

    def test_create_paper_increases_rep_by_1(self):
        user = create_random_default_user('Ronald')
        create_paper(uploaded_by=user)

        self.assertEqual(user.reputation, 2)

    def test_comment_upvoted_increases_rep_by_5(self):
        recipient = create_random_default_user('Ginny')
        comment = create_comment(created_by=recipient)
        upvote_comment(comment, self.user)

        self.assertEqual(recipient.reputation, 6)

    def test_comment_downvoted_decreases_rep_by_1(self):
        recipient = create_random_default_user('Fred')
        comment = create_comment(created_by=recipient)
        downvote_comment(comment, self.user)

        self.assertEqual(recipient.reputation, 0)

    def test_multiple_reputation_distributions(self):
        self.assertEqual(self.recipient.reputation, 1)

        comment = create_comment(created_by=self.recipient)
        vote = upvote_comment(comment, self.user)

        self.assertEqual(self.recipient.reputation, 6)

        update_to_downvote(vote)

        self.assertEqual(self.recipient.reputation, 5)
