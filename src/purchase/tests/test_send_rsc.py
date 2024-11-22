from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APITestCase

from discussion.tests.helpers import create_rh_comment
from paper.tests.helpers import create_paper
from purchase.models import Balance
from reputation.models import BountyFee, Escrow, SupportFee
from researchhub_document.helpers import create_post
from user.related_models.gatekeeper_model import Gatekeeper
from user.tests.helpers import (
    create_moderator,
    create_random_authenticated_user,
    create_random_default_user,
    create_user,
)
from utils.test_helpers import (
    IntegrationTestHelper,
    TestHelper,
    get_authenticated_post_response,
)


class SendRSCTest(APITestCase, TestCase, TestHelper, IntegrationTestHelper):
    base_url = "/api/transactions/send_rsc/"
    balance_amount = 50

    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.bountyFee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)
        self.supportFee = SupportFee.objects.create(rh_pct=0.03, dao_pct=0.00)
        self.recipient = create_random_default_user("recipient")

    def test_list_purchases(self):
        purchaser = create_random_authenticated_user("rep_user")
        poster = create_random_authenticated_user("rep_user")
        post = create_post(created_by=poster)

        tip_amount = 100

        # give the user 10,000 RSC
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount="10000", user=purchaser, content_type=DISTRIBUTION_CONTENT_TYPE
        )

        response = self._post_support_response(
            purchaser, post.id, "researchhubpost", tip_amount
        )
        self.assertContains(response, "id", status_code=201)

        self.client.force_authenticate(purchaser)
        response = self.client.get("/api/purchase/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    def test_list_purchases_cannot_list_other_users_purchases(self):
        purchaser = create_random_authenticated_user("rep_user")
        poster = create_random_authenticated_user("rep_user")
        post = create_post(created_by=poster)

        tip_amount = 100

        # give the user 10,000 RSC
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount="10000", user=purchaser, content_type=DISTRIBUTION_CONTENT_TYPE
        )

        response = self._post_support_response(
            purchaser, post.id, "researchhubpost", tip_amount
        )
        self.assertContains(response, "id", status_code=201)

        self.client.force_authenticate(poster)
        response = self.client.get("/api/purchase/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 0)

    def test_regular_user_send_rsc(self):
        client = self.get_default_authenticated_client()
        response = self._send_rsc(client, self.recipient)
        self.assertEqual(response.status_code, 403)

    def test_gatekeeper_send_rsc(self):
        moderator = create_moderator(first_name="moderator", last_name="moderator")
        Gatekeeper.objects.create(type="SEND_RSC", user=moderator)
        self.client.force_authenticate(moderator)
        response = self._send_rsc(self.client, self.recipient)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.recipient.balances.count(), 1)
        self.assertEqual(
            int(self.recipient.balances.first().amount), self.balance_amount
        )

    def test_moderator_user_send_rsc(self):
        moderator = create_moderator(first_name="moderator", last_name="moderator")
        self.client.force_authenticate(moderator)
        response = self._send_rsc(self.client, self.recipient)
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_send_rsc(self):
        response = self._send_rsc(self.client, self.recipient)
        self.assertEqual(response.status_code, 401)

    def _send_rsc(self, client, user):
        url = self.base_url
        form_data = self._build_form(user)
        response = client.post(url, form_data)
        return response

    def _build_form(self, user):
        form = {"recipient_id": user.id, "amount": self.balance_amount}
        return form

    def test_support_paper_distribution(self):
        user = create_random_authenticated_user("rep_user")
        uploader = create_random_authenticated_user("rep_user")
        paper = create_paper(uploaded_by=uploader)
        amount = 10

        # give the user 10,000 RSC
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount="10000", user=user, content_type=DISTRIBUTION_CONTENT_TYPE
        )

        response = self._post_support_response(user, paper.id, "paper", amount)
        self.assertContains(response, "id", status_code=201)
        self.assertTrue(Escrow.objects.filter(hold_type=Escrow.AUTHOR_RSC).count() == 1)
        author_pot = Escrow.objects.filter(hold_type=Escrow.AUTHOR_RSC).first()
        self.assertTrue(author_pot.amount_holding == amount)

    def test_support_post_distribution(self):
        user = create_random_authenticated_user("rep_user")
        poster = create_random_authenticated_user("rep_user")
        post = create_post(created_by=poster)

        tip_amount = 100
        fee_amount = 3  # latest `SupportFee` is 3% RH, 0% DAO as of 2024-01-19

        # give the user 10,000 RSC
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount="10000", user=user, content_type=DISTRIBUTION_CONTENT_TYPE
        )

        response = self._post_support_response(
            user, post.id, "researchhubpost", tip_amount
        )
        self.assertContains(response, "id", status_code=201)
        purchase_id = response.data["id"]
        # fee and balance deducted from user
        fee_balance_entry = Balance.objects.filter(
            user=user,
            content_type=ContentType.objects.get_for_model(SupportFee),
        )
        self.assertTrue(fee_balance_entry.exists())
        balance_fee_amount = float(fee_balance_entry.first().amount)
        self.assertEqual(balance_fee_amount, float(-fee_amount))
        amount_balance_entry = Balance.objects.filter(
            user=user,
            content_type=ContentType.objects.get(model="purchase"),
            object_id=purchase_id,
        )
        self.assertTrue(amount_balance_entry.exists())
        tip_balance_amount = float(amount_balance_entry.first().amount)
        self.assertEqual(tip_balance_amount, float(-tip_amount))
        # balance added to poster
        poster_balance_entry = Balance.objects.filter(
            user=poster,
            content_type=ContentType.objects.get(model="distribution"),
        )
        self.assertTrue(poster_balance_entry.exists())
        poster_balance_amount = float(
            poster_balance_entry.latest("created_date").amount
        )
        self.assertEqual(poster_balance_amount, float(tip_amount))

    def test_support_comment_distribution(self):
        user = create_random_authenticated_user("rep_user")
        poster = create_random_authenticated_user("rep_user")
        post = create_post(created_by=poster)
        comment = create_rh_comment(created_by=poster, post=post)

        tip_amount = 100
        fee_amount = 3

        # give the user 10,000 RSC
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount="10000", user=user, content_type=DISTRIBUTION_CONTENT_TYPE
        )

        response = self._post_support_response(
            user, comment.id, "rhcommentmodel", tip_amount
        )
        self.assertContains(response, "id", status_code=201)
        purchase_id = response.data["id"]
        # fee and balance deducted from user
        fee_balance_entry = Balance.objects.filter(
            user=user,
            content_type=ContentType.objects.get_for_model(SupportFee),
        )
        self.assertTrue(fee_balance_entry.exists())
        balance_fee_amount = float(fee_balance_entry.first().amount)
        self.assertEqual(balance_fee_amount, float(-fee_amount))
        amount_balance_entry = Balance.objects.filter(
            user=user,
            content_type=ContentType.objects.get(model="purchase"),
            object_id=purchase_id,
        )
        self.assertTrue(amount_balance_entry.exists())
        tip_balance_amount = float(amount_balance_entry.first().amount)
        self.assertEqual(tip_balance_amount, float(-tip_amount))
        # balance added to poster
        poster_balance_entry = Balance.objects.filter(
            user=poster,
            content_type=ContentType.objects.get(model="distribution"),
        )
        self.assertTrue(poster_balance_entry.exists())
        poster_balance_amount = float(
            poster_balance_entry.latest("created_date").amount
        )
        self.assertEqual(poster_balance_amount, float(tip_amount))

    def _post_support_response(self, user, object_id, content_type, amount=10):
        url = "/api/purchase/"
        return get_authenticated_post_response(
            user,
            url,
            {
                "amount": amount,
                "content_type": content_type,
                "object_id": object_id,
                "purchase_method": "OFF_CHAIN",
                "purchase_type": "BOOST",
            },
        )

    def test_probable_spammer_cannot_support(self):
        user = create_random_authenticated_user("spammer_user")
        poster = create_random_authenticated_user("poster_user")
        post = create_post(created_by=poster)

        # Set user as probable spammer
        user.probable_spammer = True
        user.save()

        # give the user 10,000 RSC
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount="10000", user=user, content_type=DISTRIBUTION_CONTENT_TYPE
        )

        response = self._post_support_response(user, post.id, "researchhubpost", 100)

        self.assertEqual(response.status_code, 403)

        # Verify no balance entries were created
        self.assertEqual(
            Balance.objects.filter(
                user=user, content_type=ContentType.objects.get_for_model(SupportFee)
            ).count(),
            0,
        )
        self.assertEqual(
            Balance.objects.filter(
                user=poster, content_type=ContentType.objects.get(model="distribution")
            ).count(),
            0,
        )
