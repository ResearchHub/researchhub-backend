import json
import math

from django.test import TestCase, Client

from user.models import User, Author, University
from paper.models import Vote as PaperVote
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
        create_upvote_distribution(1, self.original_paper)
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
        distribution = create_upvote_distribution(1, self.original_paper)
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
        distribution = create_upvote_distribution(1, self.original_paper)
        distribution_amount = calculate_rsc_per_upvote()
        self.assertEquals(Distribution.objects.count(), 1)
        self.assertEquals(Distribution.objects.first().amount, math.floor(distribution_amount * .75 / 3))

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

        distribution = create_upvote_distribution(1, self.original_paper)
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
