import json
import math

from django.test import TestCase, Client
from django.contrib.contenttypes.models import ContentType

from user.models import User, Author, University
from paper.models import Vote as PaperVote
from discussion.models import Vote as DiscussionVote, Thread, Reply, Comment
from utils.test_helpers import (
    IntegrationTestHelper,
    TestHelper,
    get_user_from_response
)
from reputation.distributions import calculate_rsc_per_upvote, create_upvote_distribution
from reputation.models import AuthorRSC, Distribution
from purchase.models import Balance
from researchhub_case.constants.case_constants import (
    APPROVED
)
from researchhub_case.models import AuthorClaimCase
from user.models import Author
from researchhub_case.tasks import (
    after_approval_flow,
)

class BaseTests(TestCase, TestHelper):
    def setUp(self):
        NUM_VOTES = 1
        votes = []
        user = self.create_user()
        original_paper = self.create_paper_without_authors()
        self.original_paper = original_paper
        self.user = user
        original_paper.raw_authors = [
            {'first_name': 'First', 'last_name': 'Last'}
        ]

        for x in range(NUM_VOTES):
            votes.append(PaperVote(vote_type=1, paper=original_paper, created_by=user))
        PaperVote.objects.bulk_create(votes)

    def test_upvote_distribution(
        self,
    ):
        distribution_amount = calculate_rsc_per_upvote()
        create_upvote_distribution(1, self.original_paper, PaperVote.objects.first())
        self.assertEquals(AuthorRSC.objects.count(), 1)
        self.assertEquals(AuthorRSC.objects.first().amount, math.floor(distribution_amount * .75))
    
    def test_no_verified_author_distribution(
        self,
    ):
        self.original_paper.raw_authors = [
            {'first_name': 'First', 'last_name': 'Last'},
            {'first_name': 'Jimmy', 'last_name': 'Johns'},
            {'first_name': 'Ronald', 'last_name': 'McDonald'},
        ]
        university = self.create_university()
        author_user = self.create_user(
            first_name='First',
            last_name='Last',
            email='user2@gmail.com',
        )

        if Author.objects.count() > 0:
            Author.objects.all().delete()
        
        university = self.create_university()
        author = Author.objects.create(
            user=author_user,
            first_name=self.original_paper.raw_authors[0].get('first_name'),
            last_name=self.original_paper.raw_authors[0].get('last_name'),
            university=university
        )

        self.original_paper.authors.add(author)
        distribution = create_upvote_distribution(1, self.original_paper, PaperVote.objects.first())
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(Distribution.objects.count(), 0)
        self.assertEquals(distribution.amount, distribution_amount * .25)
    
    def test_author_claim_distribution(
        self,
    ):
        self.original_paper.raw_authors = [
            {'first_name': 'First', 'last_name': 'Last'},
            {'first_name': 'Jimmy', 'last_name': 'Johns'},
            {'first_name': 'Ronald', 'last_name': 'McDonald'},
        ]

        university = self.create_university()
        author_user = self.create_user(
            first_name='First',
            last_name='Last',
            email='user3@gmail.com',
        )

        university = self.create_university()
        if Author.objects.count() > 0:
            Author.objects.all().delete()
        author = Author.objects.create(
            user=author_user,
            first_name=self.original_paper.raw_authors[0].get('first_name'),
            last_name=self.original_paper.raw_authors[0].get('last_name'),
            university=university
        )

        self.original_paper.authors.add(author)
        AuthorClaimCase.objects.create(target_paper=self.original_paper, requestor=author.user, status=APPROVED)
        distribution = create_upvote_distribution(1, self.original_paper, PaperVote.objects.first())
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(Distribution.objects.count(), 1)
        self.assertEquals(Distribution.objects.first().amount, math.floor(distribution_amount * .75 / 3))

    def test_thread_upvote_distribution(
        self
    ):
        if Distribution.objects.count() > 0:
            Distribution.objects.all().delete()

        if AuthorRSC.objects.count() > 0:
            AuthorRSC.objects.all().delete()
        
        if Author.objects.count() > 0:
            Author.objects.all().delete()
        
        new_user = self.create_user(
            first_name='First',
            last_name='Last',
            email='user3@gmail.com',
        )

        thread = Thread.objects.create(created_by=new_user, paper=self.original_paper)
        thread_ct = ContentType.objects.get(model='thread')

        thread_vote = DiscussionVote.objects.create(item=thread, content_type=thread_ct, vote_type=1, created_by=self.user)

        distribution = create_upvote_distribution(1, self.original_paper, thread_vote)
        self.assertEquals(Distribution.objects.count(), 1)
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(distribution.amount, distribution_amount)
    
    def test_comment_upvote_distribution(
        self
    ):
        if Distribution.objects.count() > 0:
            Distribution.objects.all().delete()

        if AuthorRSC.objects.count() > 0:
            AuthorRSC.objects.all().delete()
        
        if Author.objects.count() > 0:
            Author.objects.all().delete()
        
        new_user = self.create_user(
            first_name='First',
            last_name='Last',
            email='user3@gmail.com',
        )

        thread = Thread.objects.create(created_by=new_user, paper=self.original_paper)
        comment_ct = ContentType.objects.get(model='comment')
        comment = Comment.objects.create(created_by=self.user, parent=thread)
        comment_vote = DiscussionVote.objects.create(item=comment, content_type=comment_ct, vote_type=1, created_by=new_user)

        distribution = create_upvote_distribution(1, self.original_paper, comment_vote)
        self.assertEquals(Distribution.objects.count(), 1)
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(distribution.amount, distribution_amount)

    def test_reply_upvote_distribution(
        self
    ):
        if Distribution.objects.count() > 0:
            Distribution.objects.all().delete()

        if AuthorRSC.objects.count() > 0:
            AuthorRSC.objects.all().delete()
        
        if Author.objects.count() > 0:
            Author.objects.all().delete()
        
        new_user = self.create_user(
            first_name='First',
            last_name='Last',
            email='user3@gmail.com',
        )

        thread = Thread.objects.create(created_by=new_user, paper=self.original_paper)
        reply_ct = ContentType.objects.get(model='reply')
        comment = Comment.objects.create(created_by=self.user, parent=thread)
        reply = Reply.objects.create(created_by=new_user, parent=comment)
        reply_vote = DiscussionVote.objects.create(item=reply, content_type=reply_ct, vote_type=1, created_by=self.user)

        distribution = create_upvote_distribution(1, self.original_paper, reply_vote)
        self.assertEquals(Distribution.objects.count(), 1)
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(distribution.amount, distribution_amount)
    
    def test_ineligible_enhanced_distribution(
        self
    ):
        if Distribution.objects.count() > 0:
            Distribution.objects.all().delete()

        if AuthorRSC.objects.count() > 0:
            AuthorRSC.objects.all().delete()
        
        if Author.objects.count() > 0:
            Author.objects.all().delete()

        eligible_user = self.create_user(
            first_name='First',
            last_name='Last',
            email='user3@gmail.com',
        )

        eligible_user.reputation = 20000
        eligible_user.save()
        
        distribution_amount = calculate_rsc_per_upvote()
        distribution = create_upvote_distribution(1, self.original_paper, PaperVote.objects.first())
        self.assertEquals(distribution.amount, 1)

    def test_author_claim_pot(
        self,
    ):
        if Distribution.objects.count() > 0:
            Distribution.objects.all().delete()

        if AuthorRSC.objects.count() > 0:
            AuthorRSC.objects.all().delete()

        self.original_paper.raw_authors = [
            {'first_name': 'First', 'last_name': 'Last'},
            {'first_name': 'Jimmy', 'last_name': 'Johns'},
            {'first_name': 'Ronald', 'last_name': 'McDonald'},
        ]

        self.original_paper.save()

        university = self.create_university()
        author_user = self.create_user(
            first_name='First',
            last_name='Last',
            email='user3@gmail.com',
        )

        distribution = create_upvote_distribution(1, self.original_paper, PaperVote.objects.first())
        distribution_amount = calculate_rsc_per_upvote()
        
        university = self.create_university()
        if Author.objects.count() > 0:
            Author.objects.all().delete()

        author = Author.objects.create(
            user=author_user,
            first_name=self.original_paper.raw_authors[0].get('first_name'),
            last_name=self.original_paper.raw_authors[0].get('last_name'),
            university=university
        )

        self.original_paper.authors.add(author)
        case = AuthorClaimCase.objects.create(target_paper=self.original_paper, requestor=author.user, status=APPROVED)

        after_approval_flow.apply(
            (case.id,),
            priority=2,
            countdown=5
        )

        self.assertEquals(Distribution.objects.count(), 2)
        self.assertEquals(Distribution.objects.filter(distribution_type='UPVOTE_RSC_POT').first().amount, math.floor(distribution_amount * .75 / 3))
