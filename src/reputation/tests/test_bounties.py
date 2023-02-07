import time
from datetime import datetime

from rest_framework.test import APITestCase

from discussion.tests.helpers import create_comment, create_thread
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import BountyFee
from user.tests.helpers import create_moderator, create_random_default_user, create_user


class BountyViewTests(APITestCase):
    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.user = create_random_default_user("bounty_user")
        self.user_2 = create_random_default_user("bounty_user_2")
        self.user_3 = create_random_default_user("bounty_user_3")
        self.recipient = create_random_default_user("bounty_recipient")
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")
        self.paper = create_paper(uploaded_by=self.user)
        self.thread = create_thread(created_by=self.recipient)
        self.thread_response_1 = create_comment(created_by=self.user_2)
        self.thread_response_2 = create_comment(created_by=self.user_3)
        self.hub = create_hub()
        self.bountyFee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)
        self.client.force_authenticate(self.user)

        distribution = Dist("REWARD", 1000000000, give_rep=False)
        distributor = Distributor(
            distribution, self.user, self.user, time.time(), self.user
        )
        distributor.distribute()
        distributor = Distributor(
            distribution, self.user_2, self.user, time.time(), self.user
        )
        distributor.distribute()

    def test_user_can_create_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)
        return create_bounty_res

    def test_user_can_create_thread_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)
        return create_bounty_res

    def test_addiontal_user_can_create_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res_1 = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res_1.status_code, 201)

        self.client.force_authenticate(self.user_2)
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": 200,
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res_2.status_code, 201)

    def test_user_can_create_larger_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 20000,
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)
        return create_bounty_res

    def test_user_can_create_decimal_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 123.456,
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)

    def test_user_can_create_long_decimal_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 123.45679001,
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)

    def test_user_can_set_expiration_date(self):
        self.client.force_authenticate(self.user)

        expiration_time = f"{datetime(year=2050, month=1, day=1).isoformat()}Z"
        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
                "expiration_date": expiration_time,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)
        self.assertEqual(create_bounty_res.data["expiration_date"], expiration_time)

    def test_user_cant_create_invalid_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res_1 = self.client.post(
            "/api/bounty/",
            {
                "amount": "-100",
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": "--100",
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )
        create_bounty_res_3 = self.client.post(
            "/api/bounty/",
            {
                "amount": "0xFFA",
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )
        self.assertEqual(create_bounty_res_1.status_code, 402)
        self.assertEqual(create_bounty_res_2.status_code, 400)
        self.assertEqual(create_bounty_res_3.status_code, 400)

    def test_user_cant_create_low_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 49,
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 400)

    def test_user_cant_create_high_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 10000000,
                "item_object_id": self.paper.unified_document.id,
                "item_content_type": self.paper.unified_document._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 400)

    def test_user_can_approve_full_bounty(self):
        self.client.force_authenticate(self.user)

        bounty = self.test_user_can_create_bounty()
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            {
                "amount": None,
                "object_id": self.thread.id,
                "content_type": self.thread._meta.model_name,
                "recipient": self.user.id,
            },
        )

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(approve_bounty_res.data["amount"], bounty.data["amount"])

    def test_user_can_approve_thread_bounty(self):
        self.client.force_authenticate(self.user)

        bounty = self.test_user_can_create_thread_bounty()
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            {
                "amount": None,
                "object_id": self.thread.id,
                "content_type": self.thread._meta.model_name,
                "recipient": self.user.id,
            },
        )

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(approve_bounty_res.data["amount"], bounty.data["amount"])

    def test_user_can_approve_thread_bounty_single_response(self):
        self.client.force_authenticate(self.user)

        bounty = self.test_user_can_create_thread_bounty()
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            {
                "multi_bounty_approval_metadata": [
                    {
                        "recipient_id": self.user_2.id,
                        "content_type": "comment",
                        "amount": 100,
                        "object_id": self.thread_response_1.id,
                    }
                ],
                "amount": 100,
                "recipient": True,
                "object_id": True,
                "multi_approve": True,
                "content_type": "comment",
            },
        )

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(approve_bounty_res.data["amount"], bounty.data["amount"])

    def test_user_can_approve_thread_bounty_multi_response(self):
        self.client.force_authenticate(self.user)

        bounty = self.test_user_can_create_thread_bounty()
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            {
                "multi_bounty_approval_metadata": [
                    {
                        "recipient_id": self.user_2.id,
                        "content_type": "comment",
                        "amount": 50,
                        "object_id": self.thread_response_1.id,
                    },
                    {
                        "recipient_id": self.user_3.id,
                        "content_type": "comment",
                        "amount": 50,
                        "object_id": self.thread_response_2.id,
                    },
                ],
                "amount": 100,
                "recipient": True,
                "object_id": True,
                "multi_approve": True,
                "content_type": "comment",
            },
        )

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(approve_bounty_res.data["amount"], bounty.data["amount"])

    def test_user_can_approve_partial_bounty(self):
        self.client.force_authenticate(self.user)

        initial_user_balance = self.user.get_balance()
        initial_recipient_balance = self.recipient.get_balance()
        bounty_1 = self.test_user_can_create_bounty()
        approve_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/approve_bounty/",
            {
                "amount": 50,
                "object_id": self.thread.id,
                "content_type": self.thread._meta.model_name,
                "recipient": self.user.id,
            },
        )

        self.assertEqual(approve_bounty_res_1.status_code, 200)
        self.assertEqual(approve_bounty_res_1.data["amount"], bounty_1.data["amount"])

        bounty_2 = self.test_user_can_create_larger_bounty()
        approve_bounty_res_2 = self.client.post(
            f"/api/bounty/{bounty_2.data['id']}/approve_bounty/",
            {
                "amount": 500,
                "object_id": self.thread.id,
                "content_type": self.thread._meta.model_name,
                "recipient": self.recipient.id,
            },
        )
        user_balance = self.user.get_balance()
        recipient_balance = self.recipient.get_balance()

        self.assertEqual(approve_bounty_res_2.status_code, 200)
        self.assertEqual(approve_bounty_res_2.data["amount"], bounty_2.data["amount"])

        self.assertGreater(recipient_balance, initial_recipient_balance)
        self.assertGreater(initial_user_balance, user_balance)

    def test_user_cant_approve_approved_bounty(self):
        self.client.force_authenticate(self.user)

        bounty = self.test_user_can_create_bounty()
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            {
                "amount": None,
                "object_id": self.thread.id,
                "content_type": self.thread._meta.model_name,
                "recipient": self.user.id,
            },
        )

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(approve_bounty_res.data["amount"], bounty.data["amount"])

        approve_bounty_res_2 = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            {
                "amount": None,
                "object_id": self.thread.id,
                "content_type": self.thread._meta.model_name,
                "recipient": self.user.id,
            },
        )
        self.assertEqual(approve_bounty_res_2.status_code, 403)

    def test_random_user_cant_approve_bounty(self):
        self.client.force_authenticate(self.user)

        bounty = self.test_user_can_create_bounty()
        self.client.force_authenticate(self.user_2)
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            {
                "amount": None,
                "object_id": self.thread.id,
                "content_type": self.thread._meta.model_name,
                "recipient": self.user.id,
            },
        )

        self.assertEqual(approve_bounty_res.status_code, 403)

    def test_user_can_cancel_bounty(self):
        self.client.force_authenticate(self.user)

        bounty_1 = self.test_user_can_create_bounty()
        cancel_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )

        self.assertEqual(cancel_bounty_res_1.status_code, 200)

    def test_random_user_cant_cancel_bounty(self):
        self.client.force_authenticate(self.user)

        bounty_1 = self.test_user_can_create_bounty()
        self.client.force_authenticate(self.user_2)
        cancel_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )

        self.assertEqual(cancel_bounty_res_1.status_code, 403)

    def test_user_cant_cancel_cancelled_bounty(self):
        self.client.force_authenticate(self.user)

        bounty_1 = self.test_user_can_create_bounty()
        self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )
        cancel_bounty_res_2 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )
        self.assertEqual(cancel_bounty_res_2.status_code, 403)
