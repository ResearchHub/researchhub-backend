import random
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from discussion.tests.helpers import (
    create_comment,
    create_reply,
    create_thread,
    endorse_discussion,
    flag_discussion,
    upvote_discussion,
    downvote_discussion,
    update_to_upvote,
    update_to_downvote
)
from paper.tests.helpers import create_paper, upvote_paper
from user.models import Author
from user.tests.helpers import (
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
        self.paper = create_paper(title='Signal Test Paper')
        self.author = create_random_authenticated_user('Dumbledore')

        self.paper.authors.add(Author.objects.get(user=self.author))
        self.paper.save()

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

    def test_comment_flagged_decreases_rep_by_2(self):
        recipient = create_random_default_user('Ed')
        comment = create_comment(created_by=recipient)
        flag_discussion(comment, self.user)

        self.assertEqual(recipient.reputation, -1)

    def test_reply_flagged_decreases_rep_by_2(self):
        recipient = create_random_default_user('Edd')
        reply = create_reply(created_by=recipient)
        flag_discussion(reply, self.user)

        self.assertEqual(recipient.reputation, -1)

    def test_thread_flagged_decreases_rep_by_2(self):
        recipient = create_random_default_user('Eddie')
        thread = create_thread(created_by=recipient)
        flag_discussion(thread, self.user)

        self.assertEqual(recipient.reputation, -1)

    def test_comment_endorsed_increases_rep_by_15(self):
        recipient = create_random_default_user('Malfoy')
        comment = create_comment(created_by=recipient)
        endorse_discussion(comment, self.author)

        self.assertEqual(recipient.reputation, 16)

    def test_reply_endorsed_decreases_rep_by_2(self):
        recipient = create_random_default_user('Crab')
        reply = create_reply(created_by=recipient)
        endorse_discussion(reply, self.author)

        self.assertEqual(recipient.reputation, 16)

    def test_thread_endorsed_decreases_rep_by_2(self):
        recipient = create_random_default_user('Goyle')
        thread = create_thread(created_by=recipient)
        endorse_discussion(thread, self.author)

        self.assertEqual(recipient.reputation, 16)

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
        runs = 90
        delay = 0.01

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
