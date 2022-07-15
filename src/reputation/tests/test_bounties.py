import time
from datetime import datetime

from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from user.tests.helpers import (
    create_moderator,
    create_random_default_user,
    create_thread,
)


class BountyViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("bounty_user")
        self.recipient = create_random_default_user("bounty_recipient")
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")
        self.thread = create_thread()
        self.hub = create_hub()
        self.client.force_authenticate(self.user)

        distribution = Dist("REWARD", 1000000000, give_rep=False)
        distributor = Distributor(
            distribution, self.user, self.user, time.time(), self.user
        )
        distributor.distribute()

    def test_user_can_create_bounty(self):
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

    def test_user_can_create_larger_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 20000,
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
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
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)

    def test_user_can_create_long_decimal_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 123.4567900001,
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
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
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
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
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
            },
        )
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": "--100",
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
            },
        )
        create_bounty_res_3 = self.client.post(
            "/api/bounty/",
            {
                "amount": "0xFFA",
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
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
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 400)

    def test_user_cant_create_high_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 10000000,
                "item_object_id": self.thread.id,
                "item_content_type": self.thread._meta.model_name,
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
                "solution_object_id": self.thread.id,
                "solution_content_type": self.thread._meta.model_name,
                "recipient": self.user.id,
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
                "solution_object_id": self.thread.id,
                "solution_content_type": self.thread._meta.model_name,
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
                "solution_object_id": self.thread.id,
                "solution_content_type": self.thread._meta.model_name,
                "recipient": self.recipient.id,
            },
        )
        user_balance = self.user.get_balance()
        recipient_balance = self.recipient.get_balance()

        self.assertEqual(approve_bounty_res_2.status_code, 200)
        self.assertEqual(approve_bounty_res_2.data["amount"], bounty_2.data["amount"])

        self.assertGreater(recipient_balance, initial_recipient_balance)
        self.assertGreater(initial_user_balance, user_balance)