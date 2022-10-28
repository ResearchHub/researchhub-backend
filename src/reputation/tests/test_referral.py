import time
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework.test import APITestCase

from discussion.tests.helpers import create_thread
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import BountyFee, Distribution
from researchhub.settings import REFERRAL_PROGRAM
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.tests.helpers import create_moderator, create_random_default_user, create_user


class ReferralTests(APITestCase):
    def setUp(self):
        self.referrer_user = create_user(email="referrer@example.com")
        self.invited_user = create_user(email="invited@example.com")
        self.random_user = create_user(email="random@example.com")
        self.invited_user.invited_by_id = self.referrer_user.id
        self.invited_user.save()

        self.author = create_random_default_user("author")
        self.non_author = create_random_default_user("non_author")
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")

        self.hub = create_hub()
        self.client.force_authenticate(self.author)

        # Create org
        response = self.client.post("/api/organization/", {"name": "test org"})
        self.org = response.data

        # Create Note
        note_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        self.note = note_response.data

        # Create Note version
        note_version_response = self.client.post(
            "/api/note_content/",
            {
                "full_src": "test content",
                "note": self.note["id"],
                "plain_text": "test content",
            },
        )
        self.note_version = note_version_response.data

        # Author Publish
        doc_response = self.client.post(
            "/api/researchhub_post/",
            {
                "document_type": "DISCUSSION",
                "full_src": "body",
                "renderable_text": "body",
                "title": "title",
                "note_id": self.note["id"],
                "hubs": [self.hub.id],
                "authors": [self.author.author_profile.id],
            },
        )

        self.post = doc_response.data

    def test_referrer_earns_commission_when_invited_receives_upvotes(self):
        # Invited user created a comment
        thread = create_thread(
            created_by=self.invited_user,
            post=ResearchhubPost.objects.get(id=self.post["id"]),
        )

        # Random user upvotes
        self.client.force_authenticate(self.random_user)
        upvote = self.client.post(
            f'/api/researchhub_post/{self.post["id"]}/discussion/{thread.id}/upvote/'
        )

        res = Distribution.objects.filter(
            distribution_type=REFERRAL_PROGRAM["REFERER_DISTRIBUTION_TYPE"],
            recipient=self.referrer_user,
        )
        self.assertEqual(res.exists(), True)
        self.assertEqual(res.count(), 1)

    def test_referrer_stop_earning_commission_after_eligiblity_expires(self):
        # set up invited user
        invited_user = create_user(email="invited2@example.com")
        invited_user.invited_by_id = self.referrer_user.id
        invited_user.created_date = timezone.now().date() - relativedelta(
            months=REFERRAL_PROGRAM["ELIGIBLE_TIME_PERIOD_IN_MONTHS"], days=1
        )
        invited_user.save()

        # Invited user created a comment
        thread = create_thread(
            created_by=invited_user,
            post=ResearchhubPost.objects.get(id=self.post["id"]),
        )

        # Random user upvotes
        self.client.force_authenticate(self.random_user)
        upvote = self.client.post(
            f'/api/researchhub_post/{self.post["id"]}/discussion/{thread.id}/upvote/'
        )

        # Ensure no referral earnings to referrer
        res = Distribution.objects.filter(
            distribution_type=REFERRAL_PROGRAM["REFERER_DISTRIBUTION_TYPE"],
            recipient=self.referrer_user,
        )
        self.assertEqual(res.exists(), False)
        self.assertEqual(res.count(), 0)

    def test_referrer_earns_specific_commission(self):
        # Invited user created a comment
        thread = create_thread(
            created_by=self.invited_user,
            post=ResearchhubPost.objects.get(id=self.post["id"]),
        )

        # Random user upvotes
        self.client.force_authenticate(self.random_user)
        upvote = self.client.post(
            f'/api/researchhub_post/{self.post["id"]}/discussion/{thread.id}/upvote/'
        )

        invited_earned = Distribution.objects.filter(recipient=self.invited_user).last()

        dist = Distribution.objects.get(
            distribution_type=REFERRAL_PROGRAM["REFERER_DISTRIBUTION_TYPE"],
            recipient=self.referrer_user,
        )
        self.assertEqual(
            int(invited_earned.amount * REFERRAL_PROGRAM["REFERER_EARN_PCT"]),
            dist.amount,
        )

    def test_if_referrer_is_giver_no_commission_is_earned(self):
        # Invited user created a comment
        thread = create_thread(
            created_by=self.invited_user,
            post=ResearchhubPost.objects.get(id=self.post["id"]),
        )

        # Referrer upvotes
        self.client.force_authenticate(self.referrer_user)
        upvote = self.client.post(
            f'/api/researchhub_post/{self.post["id"]}/discussion/{thread.id}/upvote/'
        )

        dist = Distribution.objects.filter(
            distribution_type=REFERRAL_PROGRAM["REFERER_DISTRIBUTION_TYPE"],
            recipient=self.referrer_user,
        )
        self.assertEqual(dist.exists(), False)
