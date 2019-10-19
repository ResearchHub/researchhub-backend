import random
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from discussion.tests.test_helpers import (
    create_comment,
    create_reply,
    create_thread,
    upvote_discussion,
    downvote_discussion,
    update_to_upvote,
    update_to_downvote
)
from paper.test_helpers import create_paper, upvote_paper
from user.test_helpers import (
    create_random_authenticated_user,
    create_random_default_user
)
from utils.test_helpers import (
    test_concurrently
)


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


class SignalConcurrencyTests(TransactionTestCase):
    base_url = '/api/paper/'

    def setUp(self):
        SEED = 'discussion'
        self.random_generator = random.Random(SEED)
        self.user = create_random_authenticated_user('Tom Marvolo Riddle')
        self.recipient = create_random_authenticated_user('Harry James Potter')
        self.paper = create_paper(
            title='The Half Blood Prince',
            uploaded_by=self.recipient
        )
        self.thread = create_thread(
            paper=self.paper,
            created_by=self.recipient
        )
        self.comment = create_comment(
            thread=self.thread,
            created_by=self.recipient
        )
        self.reply = create_reply(
            parent=self.comment,
            created_by=self.recipient
        )

    def test_X_paper_upvotes_do_NOT_increase_reputation(self):
        runs = 2

        starting_reputation = self.recipient.reputation

        @test_concurrently(runs)
        def run():
            unique_value = self.random_generator.random()
            voter = create_random_default_user(unique_value)
            upvote_paper(self.paper, voter)
        run()

        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.reputation, starting_reputation)

    def test_X_comment_upvotes_increase_reputation_by_X(self):
        runs = 2
        delay = 1

        starting_reputation = self.recipient.reputation

        @test_concurrently(runs, delay)
        def run():
            unique_value = self.random_generator.random()
            user = create_random_authenticated_user(unique_value)
            self.get_thread_upvote_response(user)
        run()

        expected = starting_reputation + (runs * 5)

        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.reputation, expected)

    def get_thread_upvote_response(self, user):
        url = self.base_url + (
            f'{self.paper.id}/discussion/{self.thread.id}/upvote/'
        )
        client = APIClient()
        client.force_authenticate(user, user.auth_token)
        data = {}
        response = client.post(url, data, format='json')
        return response
