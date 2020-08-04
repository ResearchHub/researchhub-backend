from datetime import timedelta
import random

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
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
from oauth.tests.helpers import create_social_account
from paper.tests.helpers import create_flag, create_paper, upvote_paper
from reputation import distributions
from reputation.signals import NEW_USER_BONUS_DAYS_LIMIT
from summary.tests.helpers import create_summary
from user.models import Author
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_default_user
)
from utils.test_helpers import (
    test_concurrently,
    get_authenticated_post_response
)


class SignalTests(TestCase):

    def setUp(self):
        self.user = create_random_default_user('Molly')
        self.recipient = create_random_default_user('Harry')
        self.paper = create_paper(title='Signal Test Paper')
        self.author = create_random_authenticated_user('Dumbledore')

        self.paper.authors.add(Author.objects.get(user=self.author))
        self.paper.save()

        self.sign_up_bonus = 25
        self.start_rep = 100 + self.sign_up_bonus
        self.new_user_create_rep = 1
        self.author_create_rep = (
            self.new_user_create_rep
            + distributions.CreateAuthoredPaper.amount
        )

    def test_create_paper_increases_rep_by_1(self):
        user = create_random_default_user('Ronald')
        create_paper(uploaded_by=user)

        user.refresh_from_db()
        self.assertEqual(user.reputation, self.start_rep + 1)

    def test_create_paper_uploaded_by_orcid_author_increases_rep_10(self):
        user = create_random_default_user('Ronald the ORCID Author')
        social = create_social_account(OrcidProvider.id, user)
        user.author_profile.orcid_id = social.uid
        user.author_profile.save()

        paper = create_paper(uploaded_by=user)
        paper.authors.add(user.author_profile)

        user.refresh_from_db()
        self.assertEqual(user.reputation, self.start_rep + 10)

    def test_create_paper_uploaded_by_non_orcid_author_increases_rep_1(self):
        user = create_random_default_user('Ronald the Author')
        paper = create_paper(uploaded_by=user)
        paper.authors.add(user.author_profile)

        user.refresh_from_db()
        self.assertEqual(user.reputation, self.start_rep + 1)

    def test_vote_on_paper_increases_rep_by_1(self):
        recipient = create_random_default_user('Luna')
        upvote_paper(self.paper, recipient)

        recipient.refresh_from_db()
        self.assertEqual(recipient.reputation, self.start_rep + 1)

    def test_vote_on_paper_ONLY_increases_rep_in_new_user(self):
        recipient = create_random_default_user('Xenophilius')
        upvote_paper(self.paper, recipient)
        recipient.refresh_from_db()

        recipient.date_joined = timezone.now() - timedelta(
            days=NEW_USER_BONUS_DAYS_LIMIT
        )
        recipient.save()
        paper = create_paper(title='Rep increase first week paper')
        upvote_paper(paper, recipient)

        recipient.refresh_from_db()
        self.assertEqual(recipient.reputation, self.start_rep + 1)

    def test_vote_on_paper_ONLY_increases_rep_below_200_new_user(self):
        recipient = create_random_default_user('Xenophilius')
        upvote_paper(self.paper, recipient)
        recipient.refresh_from_db()

        recipient.date_joined = timezone.now() - timedelta(
            days=NEW_USER_BONUS_DAYS_LIMIT
        )
        recipient.save()
        paper = create_paper(title='Rep increase once paper')
        upvote_paper(paper, recipient)

        recipient.refresh_from_db()
        self.assertEqual(recipient.reputation, self.start_rep + 1)

    def test_flag_paper_increases_rep_by_1_after_3_flags(self):
        recipient_1 = create_random_default_user('Allister')
        recipient_2 = create_random_default_user('Allister2')
        recipient_3 = create_random_default_user('Allister3')
        late_user = create_random_default_user('late user')

        create_flag(paper=self.paper, created_by=recipient_1)
        self.assertEqual(
            recipient_1.reputation + self.sign_up_bonus,
            self.start_rep
        )

        create_flag(paper=self.paper, created_by=recipient_2)
        self.assertEqual(
            recipient_1.reputation + self.sign_up_bonus,
            self.start_rep
        )

        earned_rep = distributions.FlagPaper.amount

        create_flag(paper=self.paper, created_by=recipient_3)
        recipient_1.refresh_from_db()
        recipient_2.refresh_from_db()
        recipient_3.refresh_from_db()
        self.assertEqual(recipient_1.reputation, self.start_rep + earned_rep)
        self.assertEqual(recipient_2.reputation, self.start_rep + earned_rep)
        self.assertEqual(recipient_3.reputation, self.start_rep + earned_rep)

        create_flag(paper=self.paper, created_by=late_user)
        late_user.refresh_from_db()
        self.assertEqual(late_user.reputation, self.start_rep)

    def test_create_comment_increases_rep_by_1_in_new_user(self):
        user = create_random_default_user('Ludo')
        create_comment(created_by=user)

        user.refresh_from_db()
        self.assertEqual(user.reputation, self.start_rep + 1)

        old_user = create_random_default_user('Bagman')
        old_user.date_joined = timezone.now() - timedelta(
            days=NEW_USER_BONUS_DAYS_LIMIT
        )
        old_user.save()
        create_comment(created_by=old_user)

        old_user.refresh_from_db()
        # Add bonus here because this amount is added by a signal and gets
        # wiped with refresh from db
        self.assertEqual(
            old_user.reputation + self.sign_up_bonus,
            self.start_rep
        )

    def test_create_comment_ONLY_increases_rep_under_200_new_user(self):
        user = create_random_default_user('Winky')
        create_comment(created_by=user)

        user.refresh_from_db()
        self.assertEqual(user.reputation, self.start_rep + 1)

        user.reputation = 200
        user.save()
        create_comment(created_by=user)

        user.refresh_from_db()
        self.assertEqual(user.reputation, 200)

    def test_comment_by_paper_orcid_author_upvoted_increases_rep_5(self):
        recipient = create_random_default_user('Winky the ORCID Author')
        social = create_social_account(OrcidProvider.id, recipient)
        recipient.author_profile.orcid_id = social.uid
        recipient.author_profile.save()

        paper = create_paper()
        paper.authors.add(recipient.author_profile)

        thread = create_thread(paper=paper)
        comment = create_comment(thread=thread, created_by=recipient)

        upvote_discussion(comment, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep + 5
        )

    def test_comment_by_paper_non_orcid_author_upvoted_increases_rep_1(self):
        recipient = create_random_default_user('Winky the Author')

        paper = create_paper()
        paper.authors.add(recipient.author_profile)

        thread = create_thread(paper=paper)
        comment = create_comment(thread=thread, created_by=recipient)

        upvote_discussion(comment, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep + 1
        )

    def test_comment_downvoted_decreases_rep_by_1(self):
        recipient = create_random_default_user('Fred')
        comment = create_comment(created_by=recipient)
        downvote_discussion(comment, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep - 1
        )

    def test_create_reply_increases_rep_by_1_in_new_user(self):
        user = create_random_default_user('Bathilda')
        create_reply(created_by=user)

        user.refresh_from_db()
        self.assertEqual(user.reputation, self.start_rep + 1)

        old_user = create_random_default_user('Bagshot')
        old_user.date_joined = timezone.now() - timedelta(
            days=NEW_USER_BONUS_DAYS_LIMIT
        )
        old_user.save()
        create_reply(created_by=old_user)

        old_user.refresh_from_db()
        self.assertEqual(
            old_user.reputation + self.sign_up_bonus,
            self.start_rep
        )

    def test_reply_upvoted_increases_rep_by_1(self):
        recipient = create_random_default_user('George')
        reply = create_reply(created_by=recipient)
        upvote_discussion(reply, self.user)

        earned_rep = distributions.ReplyUpvoted.amount

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep + earned_rep
        )

    def test_reply_upvoted_increases_rep_5_created_by_paper_orcid_author(self):
        recipient = create_random_default_user('George the Author')
        social = create_social_account(OrcidProvider.id, recipient)
        recipient.author_profile.orcid_id = social.uid
        recipient.author_profile.save()

        paper = create_paper()
        paper.authors.add(recipient.author_profile)

        thread = create_thread(paper=paper)
        comment = create_comment(thread=thread)
        reply = create_reply(parent=comment, created_by=recipient)

        upvote_discussion(reply, self.user)

        earned_rep = 0

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + earned_rep
        )

    def test_reply_upvoted_increases_rep_1_created_by_non_orcid_author(self):
        recipient = create_random_default_user('George the Author')

        paper = create_paper()
        paper.authors.add(recipient.author_profile)

        thread = create_thread(paper=paper)
        comment = create_comment(thread=thread)
        reply = create_reply(parent=comment, created_by=recipient)

        upvote_discussion(reply, self.user)

        earned_rep = (
            distributions.ReplyUpvoted.amount
        )

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + earned_rep
        )

    def test_reply_downvoted_decreases_rep_by_1(self):
        recipient = create_random_default_user('Bill')
        reply = create_reply(created_by=recipient)
        downvote_discussion(reply, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep - 1
        )

    def test_create_thread_increases_rep_by_1_in_new_user(self):
        user = create_random_default_user('Bellatrix')
        create_thread(created_by=user)

        user.refresh_from_db()
        self.assertEqual(user.reputation, self.start_rep + 1)

        old_user = create_random_default_user('Lestrange')
        old_user.date_joined = timezone.now() - timedelta(
            days=NEW_USER_BONUS_DAYS_LIMIT
        )
        old_user.save()
        create_reply(created_by=old_user)

        old_user.refresh_from_db()
        self.assertEqual(
            old_user.reputation + self.sign_up_bonus,
            self.start_rep
        )

    def test_thread_upvoted_increases_rep_by_5(self):
        recipient = create_random_default_user('Percy')
        thread = create_thread(created_by=recipient)
        upvote_discussion(thread, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep + 5
        )

    def test_thread_downvoted_decreases_rep_by_1(self):
        recipient = create_random_default_user('Charlie')
        thread = create_thread(created_by=recipient)
        downvote_discussion(thread, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep - 1
        )

    def test_delete_upvote_decreases_rep_by_5(self):
        recipient = create_random_default_user('Percy Delete')
        thread = create_thread(created_by=recipient)
        vote = upvote_discussion(thread, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep + 5
        )

        vote.delete()

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep
        )

    def test_delete_downvote_increases_rep_by_1(self):
        recipient = create_random_default_user('Charlie Delete')
        thread = create_thread(created_by=recipient)
        vote = downvote_discussion(thread, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep - 1
        )

        vote.delete()

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep
        )

    def test_comment_flagged_decreases_rep_by_2(self):
        recipient = create_random_default_user('Ed')
        comment = create_comment(created_by=recipient)
        flag_discussion(comment, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep - 2
        )

    def test_reply_flagged_decreases_rep_by_2(self):
        recipient = create_random_default_user('Edd')
        reply = create_reply(created_by=recipient)
        flag_discussion(reply, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep - 2
        )

    def test_thread_flagged_decreases_rep_by_2(self):
        recipient = create_random_default_user('Eddie')
        thread = create_thread(created_by=recipient)
        flag_discussion(thread, self.user)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep - 2
        )

    def test_comment_endorsed_increases_rep_by_15(self):
        recipient = create_random_default_user('Malfoy')
        comment = create_comment(created_by=recipient)
        endorse_discussion(comment, self.author)

        recipient.refresh_from_db()
        self.assertEqual(
            recipient.reputation,
            self.start_rep + self.new_user_create_rep + 15
        )

    def test_create_first_summary_increases_rep_by_5(self):
        user = create_random_authenticated_user('Lavender first summary')
        paper = create_paper(uploaded_by=user)
        self.get_first_summary_post_response(user, paper.id)
        earned_rep = (
            self.new_user_create_rep  # paper
            + self.new_user_create_rep  # summary
            + 5  # first summary
        )

        user.refresh_from_db()
        self.assertEqual(user.reputation, self.start_rep + earned_rep)

        next_user = create_random_authenticated_user('Brown next user')
        self.get_summary_post_response(next_user, paper.id)

        next_user.refresh_from_db()
        self.assertEqual(
            next_user.reputation,
            self.start_rep + self.new_user_create_rep
        )

    def test_create_summary_increases_rep_below_200_by_1_in_new_user(self):
        user = create_random_default_user('Lavender')
        create_summary('', user, self.paper.id)

        user.refresh_from_db()
        self.assertEqual(user.reputation, self.start_rep + 1)

        old_user = create_random_default_user('Brown')
        old_user.date_joined = timezone.now() - timedelta(
            days=NEW_USER_BONUS_DAYS_LIMIT
        )
        old_user.save()
        create_summary('', old_user, self.paper.id)

        old_user.refresh_from_db()
        self.assertEqual(
            old_user.reputation + self.sign_up_bonus,
            self.start_rep
        )

        rich_user = create_random_default_user('Muggle')
        rich_user.reputation = 200
        rich_user.save()
        rich_user.refresh_from_db()
        create_summary('', rich_user, self.paper.id)

        rich_user.refresh_from_db()
        self.assertEqual(rich_user.reputation, 200)

    # TODO: I think this should be increases?
    # def test_reply_endorsed_decreases_rep_by_2(self):
    #     recipient = create_random_default_user('Crab')
    #     reply = create_reply(created_by=recipient)
    #     endorse_discussion(reply, self.author)

    #     self.assertEqual(recipient.reputation, 16)

    # TODO: I think this should be increases?
    # def test_thread_endorsed_decreases_rep_by_2(self):
    #     recipient = create_random_default_user('Goyle')
    #     thread = create_thread(created_by=recipient)
    #     endorse_discussion(thread, self.author)

    #     self.assertEqual(recipient.reputation, 16)

    def test_multiple_reputation_distributions(self):
        thread = create_thread(created_by=self.recipient)
        current_rep = self.start_rep + self.new_user_create_rep

        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.reputation, current_rep)

        comment = create_comment(thread=thread, created_by=self.recipient)
        comment_vote = upvote_discussion(comment, self.user)
        current_rep = current_rep + 1 + self.new_user_create_rep

        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.reputation, current_rep)

        update_to_downvote(comment_vote)
        current_rep = current_rep - 1

        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.reputation, current_rep)

        reply = create_reply(parent=comment, created_by=self.recipient)
        reply_vote = downvote_discussion(reply, self.user)
        current_rep = current_rep - 1 + self.new_user_create_rep

        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.reputation, current_rep)

        update_to_upvote(reply_vote)
        current_rep += 1

        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.reputation, current_rep)

    def get_first_summary_post_response(self, user, paper_id):
        url = '/api/summary/first/'
        data = {'paper': paper_id, 'summary': 'summary text'}
        return get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )

    def get_summary_post_response(self, user, paper_id):
        url = '/api/summary/'
        data = {'paper': paper_id, 'summary': 'summary text'}
        return get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )


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

    def test_X_paper_upvotes_do_NOT_increase_uploader_reputation_by_X(self):
        runs = 90

        self.recipient.refresh_from_db()
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
        delay = 0

        self.recipient.refresh_from_db()
        starting_reputation = self.recipient.reputation

        @test_concurrently(runs, delay)
        def run():
            unique_value = self.random_generator.random()
            user = create_random_authenticated_user(unique_value)
            self.get_thread_upvote_response(user)
        run()

        expected = starting_reputation + (runs * 5)

        self.recipient.refresh_from_db()
        # print('start', starting_reputation, 'runs', runs, 'rate', 5, 'rep', self.recipient.reputation)  # noqa: E501
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
