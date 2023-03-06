import math

from django.contrib.admin.options import get_content_type_for_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from discussion.models import Comment, Reply, Thread
from discussion.models import Vote as GrmVote
from reputation.distributions import (
    calculate_rsc_per_upvote,
    create_upvote_distribution,
)
from reputation.models import Distribution, Escrow
from researchhub_case.constants.case_constants import APPROVED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.tasks import after_approval_flow
from user.models import Author
from utils.test_helpers import TestHelper


class BaseTests(TestCase, TestHelper):
    def setUp(self):
        NUM_VOTES = 1
        votes = []
        user = self.create_user()
        original_paper = self.create_paper_without_authors()
        self.original_paper = original_paper
        self.user = user
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

    def test_upvote_distribution(
        self,
    ):
        distribution_amount = calculate_rsc_per_upvote()
        create_upvote_distribution(1, self.original_paper, GrmVote.objects.first())
        self.assertEquals(Escrow.objects.filter(hold_type=Escrow.AUTHOR_RSC).count(), 1)
        self.assertEquals(
            Escrow.objects.filter(hold_type=Escrow.AUTHOR_RSC).first().amount_holding,
            distribution_amount * 0.75,
        )

    def test_no_verified_author_distribution(
        self,
    ):
        self.original_paper.raw_authors = [
            {"first_name": "First", "last_name": "Last"},
            {"first_name": "Jimmy", "last_name": "Johns"},
            {"first_name": "Ronald", "last_name": "McDonald"},
        ]
        university = self.create_university()
        author_user = self.create_user(
            first_name="First",
            last_name="Last",
            email="user2@gmail.com",
        )

        if Author.objects.count() > 0:
            Author.objects.all().delete()

        university = self.create_university()
        author = Author.objects.create(
            user=author_user,
            first_name=self.original_paper.raw_authors[0].get("first_name"),
            last_name=self.original_paper.raw_authors[0].get("last_name"),
            university=university,
        )

        self.original_paper.authors.add(author)
        distribution = create_upvote_distribution(
            1, self.original_paper, GrmVote.objects.first()
        )
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(Distribution.objects.count(), 0)
        self.assertEquals(distribution.amount, distribution_amount * 0.25)

    def test_author_claim_distribution(
        self,
    ):
        self.original_paper.raw_authors = [
            {"first_name": "First", "last_name": "Last"},
            {"first_name": "Jimmy", "last_name": "Johns"},
            {"first_name": "Ronald", "last_name": "McDonald"},
        ]

        university = self.create_university()
        author_user = self.create_user(
            first_name="First",
            last_name="Last",
            email="user3@gmail.com",
        )

        university = self.create_university()
        if Author.objects.count() > 0:
            Author.objects.all().delete()
        author = Author.objects.create(
            user=author_user,
            first_name=self.original_paper.raw_authors[0].get("first_name"),
            last_name=self.original_paper.raw_authors[0].get("last_name"),
            university=university,
        )

        self.original_paper.authors.add(author)
        AuthorClaimCase.objects.create(
            target_paper=self.original_paper, requestor=author.user, status=APPROVED
        )
        distribution = create_upvote_distribution(
            1, self.original_paper, GrmVote.objects.first()
        )
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(Distribution.objects.count(), 1)
        self.assertEquals(
            Distribution.objects.first().amount,
            math.floor(distribution_amount * 0.75 / 3),
        )

    def test_thread_upvote_distribution(self):
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

        self.user.reputation = 50000
        self.user.save()

        thread = Thread.objects.create(created_by=new_user, paper=self.original_paper)
        thread_ct = ContentType.objects.get(model="thread")

        thread_vote = GrmVote.objects.create(
            item=thread, content_type=thread_ct, vote_type=1, created_by=self.user
        )

        distribution = create_upvote_distribution(1, None, thread_vote)
        self.assertEquals(Distribution.objects.count(), 1)
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(distribution.amount, distribution_amount)

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

        new_user.reputation = 50000
        new_user.save()

        thread = Thread.objects.create(created_by=new_user, paper=self.original_paper)
        comment_ct = ContentType.objects.get(model="comment")
        comment = Comment.objects.create(created_by=self.user, parent=thread)
        comment_vote = GrmVote.objects.create(
            item=comment, content_type=comment_ct, vote_type=1, created_by=new_user
        )

        distribution = create_upvote_distribution(1, None, comment_vote)
        self.assertEquals(Distribution.objects.count(), 1)
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(distribution.amount, distribution_amount)

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

        self.user.reputation = 50000
        self.user.save()

        thread = Thread.objects.create(created_by=new_user, paper=self.original_paper)
        reply_ct = ContentType.objects.get(model="reply")
        comment = Comment.objects.create(created_by=self.user, parent=thread)
        reply = Reply.objects.create(created_by=new_user, parent=comment)
        reply_vote = GrmVote.objects.create(
            item=reply, content_type=reply_ct, vote_type=1, created_by=self.user
        )

        distribution = create_upvote_distribution(1, None, reply_vote)
        self.assertEquals(Distribution.objects.count(), 1)
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(distribution.amount, distribution_amount)
        reply_vote.vote_type = 2
        reply_vote.save()
        reply_vote.vote_type = 1
        reply_vote.save()
        self.assertEquals(Distribution.objects.count(), 1)
        self.assertEquals(distribution.amount, distribution_amount)

    def test_reply_upvote_distribution(self):
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

        self.user.reputation = 50000
        self.user.save()

        thread = Thread.objects.create(created_by=new_user, paper=self.original_paper)
        reply_ct = ContentType.objects.get(model="reply")
        comment = Comment.objects.create(created_by=self.user, parent=thread)
        reply = Reply.objects.create(created_by=new_user, parent=comment)
        reply_vote = GrmVote.objects.create(
            item=reply, content_type=reply_ct, vote_type=1, created_by=self.user
        )

        distribution = create_upvote_distribution(1, None, reply_vote)
        self.assertEquals(Distribution.objects.count(), 1)
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(distribution.amount, distribution_amount)

    def test_ineligible_enhanced_distribution(self):
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

        distribution_amount = calculate_rsc_per_upvote()
        distribution = create_upvote_distribution(
            1, self.original_paper, GrmVote.objects.first()
        )
        self.assertEquals(distribution.amount, 1)

    def test_author_claim_pot(
        self,
    ):
        if Distribution.objects.count() > 0:
            Distribution.objects.all().delete()

        if Escrow.objects.count() > 0:
            Escrow.objects.all().delete()

        self.original_paper.raw_authors = [
            {"first_name": "First", "last_name": "Last"},
            {"first_name": "Jimmy", "last_name": "Johns"},
            {"first_name": "Ronald", "last_name": "McDonald"},
        ]

        self.original_paper.save()

        university = self.create_university()
        author_user = self.create_user(
            first_name="First",
            last_name="Last",
            email="user3@gmail.com",
        )

        distribution = create_upvote_distribution(
            1, self.original_paper, GrmVote.objects.first()
        )
        distribution_amount = calculate_rsc_per_upvote()

        university = self.create_university()
        if Author.objects.count() > 0:
            Author.objects.all().delete()

        author = Author.objects.create(
            user=author_user,
            first_name=self.original_paper.raw_authors[0].get("first_name"),
            last_name=self.original_paper.raw_authors[0].get("last_name"),
            university=university,
        )

        self.original_paper.authors.add(author)
        case = AuthorClaimCase.objects.create(
            target_paper=self.original_paper, requestor=author.user, status=APPROVED
        )

        after_approval_flow.apply((case.id,), priority=2, countdown=1)

        self.assertEquals(Distribution.objects.count(), 2)
        self.assertEquals(
            Distribution.objects.filter(distribution_type="UPVOTE_RSC_POT")
            .first()
            .amount,
            math.floor(distribution_amount * 0.75 / 3),
        )
