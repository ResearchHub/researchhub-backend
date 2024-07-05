from django.contrib.admin.options import get_content_type_for_model
from django.test import TestCase

import reputation.distributions as distributions
from discussion.models import Vote as GrmVote
from discussion.tests.helpers import create_rh_comment
from reputation.models import Distribution, Escrow
from user.models import Author
from utils.test_helpers import TestHelper


class BaseTests(TestCase, TestHelper):
    def setUp(self):
        NUM_VOTES = 1
        votes = []
        uploaded_by = self.create_user(
            first_name="paper_uploader",
            last_name="uploader",
            email="paperuploader_1239@gmail.com",
        )
        original_paper = self.create_paper_without_authors(uploaded_by=uploaded_by)
        user = self.create_user()
        self.user = user
        self.original_paper = original_paper
        original_paper.raw_authors = [{"first_name": "First", "last_name": "Last"}]

        for x in range(NUM_VOTES):
            votes.append(
                GrmVote(
                    vote_type=1,
                    object_id=original_paper.id,
                    created_by=user,
                    content_type=get_content_type_for_model(original_paper),
                )
            )
        GrmVote.objects.bulk_create(votes)

    def test_comment_upvote_distribution(self):
        if Distribution.objects.count() > 0:
            Distribution.objects.all().delete()

        if Escrow.objects.count() > 0:
            Escrow.objects.all().delete()

        if Author.objects.count() > 0:
            Author.objects.all().delete()

        new_user = self.create_user(
            first_name="First",
            last_name="Last",
            email="user3@gmail.com",
        )
        voter_user = self.create_user(
            first_name="Up", last_name="voter", email="test_voter_123_pid@gmail.com"
        )

        new_user.reputation = 50000
        new_user.save()
        comment = create_rh_comment(created_by=new_user, paper=self.original_paper)
        GrmVote.objects.create(item=comment, vote_type=1, created_by=voter_user)
        distribution = distributions.Distribution(1, 1, 1)
        self.assertEqual(Distribution.objects.count(), 1)
        self.assertEqual(distribution.amount, Distribution.objects.first().amount)

    def test_upvote_downvote_upvote(self):
        if Distribution.objects.count() > 0:
            Distribution.objects.all().delete()

        if Escrow.objects.count() > 0:
            Escrow.objects.all().delete()

        if Author.objects.count() > 0:
            Author.objects.all().delete()

        new_user = self.create_user(
            first_name="First",
            last_name="Last",
            email="user3@gmail.com",
        )
        voter_user = self.create_user(
            first_name="Up", last_name="voter", email="test_voter_123_pid@gmail.com"
        )

        self.user.reputation = 50000
        self.user.save()

        comment = create_rh_comment(created_by=new_user, paper=self.original_paper)
        reply = create_rh_comment(
            created_by=new_user, paper=self.original_paper, parent=comment
        )
        reply_vote = GrmVote.objects.create(
            item=reply, vote_type=1, created_by=voter_user
        )

        distribution = distributions.Distribution(1, 1, 1)
        self.assertEqual(Distribution.objects.count(), 1)
        self.assertEqual(distribution.amount, Distribution.objects.first().amount)
        reply_vote.vote_type = 2
        reply_vote.save()
        reply_vote.vote_type = 1
        reply_vote.save()
        self.assertEqual(Distribution.objects.count(), 1)
        self.assertEqual(distribution.amount, Distribution.objects.first().amount)

    def test_upvote_distribution(self):
        if Distribution.objects.count() > 0:
            Distribution.objects.all().delete()

        if Escrow.objects.count() > 0:
            Escrow.objects.all().delete()

        if Author.objects.count() > 0:
            Author.objects.all().delete()

        eligible_user = self.create_user(
            first_name="First",
            last_name="Last",
            email="user3@gmail.com",
        )

        eligible_user.reputation = 20000
        eligible_user.save()

        distribution = distributions.Distribution(1, 1, 1)
        self.assertEqual(distribution.amount, 1)
