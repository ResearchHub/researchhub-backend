from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from purchase.models import Balance
from reputation.models import Escrow
from user.related_models.gatekeeper_model import Gatekeeper
from user.tests.helpers import (
    create_moderator,
    create_random_authenticated_user,
    create_random_default_user,
)
from utils.test_helpers import (
    IntegrationTestHelper,
    TestHelper,
    get_authenticated_post_response,
)


# Create your tests here.
class SendRSCTest(APITestCase, TestCase, TestHelper, IntegrationTestHelper):
    base_url = "/api/transactions/send_rsc/"
    balance_amount = 50

    def setUp(self):
        self.recipient = create_random_default_user("recipient")

    def test_regular_user_send_rsc(self):
        client = self.get_default_authenticated_client()
        response = self.send_rsc(client, self.recipient)
        self.assertEqual(response.status_code, 403)

    def test_gatekeeper_send_rsc(self):
        moderator = create_moderator(first_name="moderator", last_name="moderator")
        Gatekeeper.objects.create(type="SEND_RSC", user=moderator)
        self.client.force_authenticate(moderator)
        response = self.send_rsc(self.client, self.recipient)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.recipient.balances.count(), 1)
        self.assertEqual(
            int(self.recipient.balances.first().amount), self.balance_amount
        )

    def test_moderator_user_send_rsc(self):
        moderator = create_moderator(first_name="moderator", last_name="moderator")
        self.client.force_authenticate(moderator)
        response = self.send_rsc(self.client, self.recipient)
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_send_rsc(self):
        response = self.send_rsc(self.client, self.recipient)
        self.assertEqual(response.status_code, 401)

    def send_rsc(self, client, user):
        url = self.base_url
        form_data = self.build_form(user)
        response = client.post(url, form_data)
        return response

    def build_form(self, user):
        form = {"recipient_id": user.id, "amount": self.balance_amount}
        return form

    def test_support_distribution(self):
        user = create_random_authenticated_user("rep_user")
        uploader = create_random_authenticated_user("rep_user")
        paper = create_paper(uploaded_by=uploader)
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        amount = 10

        Balance.objects.create(
            amount="10000", user=user, content_type=DISTRIBUTION_CONTENT_TYPE
        )
        response = self.post_support_response(user, paper.id, amount)
        self.assertContains(response, "id", status_code=201)
        self.assertTrue(Escrow.objects.filter(hold_type=Escrow.AUTHOR_RSC).count() == 1)
        author_pot = Escrow.objects.filter(hold_type=Escrow.AUTHOR_RSC).first()
        self.assertTrue(author_pot.amount_holding == amount * 0.75)
        self.assertTrue(Balance.objects.count() == 3)

    def post_support_response(self, user, paper_id, amount=10):
        url = "/api/purchase/"
        return get_authenticated_post_response(
            user,
            url,
            {
                "amount": amount,
                "content_type": "paper",
                "object_id": paper_id,
                "purchase_method": "OFF_CHAIN",
                "purchase_type": "BOOST",
            },
        )
