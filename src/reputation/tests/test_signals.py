from django.test import TestCase

from discussion.tests.test_helpers import (
    create_comment,
    create_reply,
    create_thread,
    upvote_discussion,
    downvote_discussion,
    update_to_upvote,
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
        upvote_discussion(comment, self.user)

        self.assertEqual(recipient.reputation, 6)

    def test_comment_downvoted_decreases_rep_by_1(self):
        recipient = create_random_default_user('Fred')
        comment = create_comment(created_by=recipient)
        downvote_discussion(comment, self.user)

        self.assertEqual(recipient.reputation, 0)

    def test_reply_upvoted_increases_rep_by_5(self):
        recipient = create_random_default_user('George')
        reply = create_reply(created_by=recipient)
        upvote_discussion(reply, self.user)

        self.assertEqual(recipient.reputation, 6)

    def test_reply_downvoted_decreases_rep_by_1(self):
        recipient = create_random_default_user('Bill')
        reply = create_reply(created_by=recipient)
        downvote_discussion(reply, self.user)

        self.assertEqual(recipient.reputation, 0)

    def test_thread_upvoted_increases_rep_by_5(self):
        recipient = create_random_default_user('Percy')
        thread = create_thread(created_by=recipient)
        upvote_discussion(thread, self.user)

        self.assertEqual(recipient.reputation, 6)

    def test_thread_downvoted_decreases_rep_by_1(self):
        recipient = create_random_default_user('Charlie')
        thread = create_thread(created_by=recipient)
        downvote_discussion(thread, self.user)

        self.assertEqual(recipient.reputation, 0)

    def test_multiple_reputation_distributions(self):
        thread = create_thread(created_by=self.recipient)
        self.assertEqual(self.recipient.reputation, 1)

        comment = create_comment(thread=thread, created_by=self.recipient)
        comment_vote = upvote_discussion(comment, self.user)

        self.assertEqual(self.recipient.reputation, 6)

        update_to_downvote(comment_vote)

        self.assertEqual(self.recipient.reputation, 5)

        reply = create_reply(parent=comment, created_by=self.recipient)
        reply_vote = downvote_discussion(reply, self.user)

        self.assertEqual(self.recipient.reputation, 4)

        update_to_upvote(reply_vote)

        self.assertEqual(self.recipient.reputation, 9)
