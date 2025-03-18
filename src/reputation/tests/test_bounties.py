import decimal
import time
from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from discussion.reaction_models import Vote
from hub.models import Hub
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Bounty, BountyFee
from researchhub_comment.tests.helpers import create_rh_comment
from user.models import User
from user.tests.helpers import create_moderator, create_random_default_user, create_user


class BountyViewTests(APITestCase):
    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.user = create_random_default_user("bounty_user")
        self.user_2 = create_random_default_user("bounty_user_2")
        self.user_3 = create_random_default_user("bounty_user_3")
        self.user_4 = create_random_default_user("bounty_user_4")
        self.recipient = create_random_default_user("bounty_recipient")
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")

        self.rh_official = create_random_default_user("rh_official")
        self.rh_official.is_official_account = True
        self.rh_official.save()

        self.thread = create_rh_comment(created_by=self.recipient)
        self.thread_response_1 = create_rh_comment(
            created_by=self.user_2, parent=self.thread
        )
        self.thread_response_2 = create_rh_comment(
            created_by=self.user_3, parent=self.thread
        )
        self.thread_response_3 = create_rh_comment(
            created_by=self.user_4, parent=self.thread
        )
        self.hub = create_hub()
        self.bountyFee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        # Create votes for the threads
        self._create_vote(self.user, self.thread, Vote.UPVOTE)
        self._create_vote(self.user_2, self.thread, Vote.UPVOTE)
        self._create_vote(self.user_3, self.thread, Vote.DOWNVOTE)

        self.client.force_authenticate(self.user)

        distribution = Dist("REWARD", 1000000000, give_rep=False)

        distributor = Distributor(
            distribution, self.user, self.user, time.time(), self.user
        )
        distributor.distribute()

        distributor = Distributor(
            distribution,
            self.rh_official,
            self.rh_official,
            time.time(),
            self.rh_official,
        )
        distributor.distribute()

        distributor = Distributor(
            distribution, self.user_2, self.user_2, time.time(), self.user_2
        )
        distributor.distribute()

        distributor = Distributor(
            distribution, self.user_3, self.user_3, time.time(), self.user_3
        )
        distributor.distribute()

        distributor = Distributor(
            distribution, self.user_4, self.user_4, time.time(), self.user_4
        )
        distributor.distribute()

    def _create_vote(self, user, item, vote_type):
        """Helper method to create votes"""
        content_type = ContentType.objects.get_for_model(item)
        vote = Vote.objects.create(
            content_type=content_type,
            object_id=item.id,
            created_by=user,
            vote_type=vote_type,
        )
        return vote

    def test_user_can_create_bounty(self, amount=100):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": amount,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)
        return create_bounty_res

    def test_user_can_contribute_to_bounty(self, amount_1=100, amount_2=200):
        self.client.force_authenticate(self.user)

        create_bounty_res_1 = self.client.post(
            "/api/bounty/",
            {
                "amount": amount_1,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(create_bounty_res_1.status_code, 201)

        self.client.force_authenticate(self.user_2)
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": amount_2,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(create_bounty_res_2.status_code, 201)
        return create_bounty_res_1, create_bounty_res_2

    def test_user_can_create_larger_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 20000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
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
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)

    def test_user_can_create_long_decimal_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 123.45679001,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)

    def test_user_cant_create_negative_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": -1234.123,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 402)

    def test_user_can_set_expiration_date(self):
        self.client.force_authenticate(self.user)

        expiration_time = f"{datetime(year=2050, month=1, day=1).isoformat()}Z"
        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
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
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": "--100",
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )
        create_bounty_res_3 = self.client.post(
            "/api/bounty/",
            {
                "amount": "0xFFA",
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
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
                "amount": 5,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 400)

    def test_user_cant_create_high_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 10000000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 400)

    def test_user_can_approve_full_bounty(self):
        self.client.force_authenticate(self.user)

        bounty = self.test_user_can_create_bounty()
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            [
                {
                    "amount": bounty.data["amount"],
                    "object_id": self.thread.id,
                    "content_type": self.thread._meta.model_name,
                }
            ],
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
            [
                {
                    "amount": decimal.Decimal(bounty_1.data["amount"]) / 2,
                    "object_id": self.thread.id,
                    "content_type": self.thread._meta.model_name,
                }
            ],
        )

        self.assertEqual(approve_bounty_res_1.status_code, 200)
        self.assertEqual(approve_bounty_res_1.data["amount"], bounty_1.data["amount"])

        bounty_2 = self.test_user_can_create_larger_bounty()
        approve_bounty_res_2 = self.client.post(
            f"/api/bounty/{bounty_2.data['id']}/approve_bounty/",
            [
                {
                    "amount": decimal.Decimal(bounty_2.data["amount"]) / 2,
                    "object_id": self.thread.id,
                    "content_type": self.thread._meta.model_name,
                }
            ],
        )
        user_balance = self.user.get_balance()
        recipient_balance = self.recipient.get_balance()

        self.assertEqual(approve_bounty_res_2.status_code, 200)
        self.assertGreater(recipient_balance, initial_recipient_balance)
        self.assertGreater(initial_user_balance, user_balance)

    def test_user_can_approve_full_multi_bounties(self):
        self.client.force_authenticate(self.user)
        amount = 600
        bounty = self.test_user_can_create_bounty(amount=amount)
        initial_user_balance = self.user.get_balance()
        initial_recipient_1_balance = self.thread_response_1.created_by.get_balance()
        initial_recipient_2_balance = self.thread_response_2.created_by.get_balance()
        initial_recipient_3_balance = self.thread_response_3.created_by.get_balance()
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            [
                {
                    "amount": amount / 3,
                    "object_id": self.thread_response_1.id,
                    "content_type": self.thread_response_1._meta.model_name,
                },
                {
                    "amount": amount / 3,
                    "object_id": self.thread_response_2.id,
                    "content_type": self.thread_response_2._meta.model_name,
                },
                {
                    "amount": amount / 3,
                    "object_id": self.thread_response_3.id,
                    "content_type": self.thread_response_3._meta.model_name,
                },
            ],
        )

        user_balance = self.user.get_balance()
        recipient_1_balance = self.thread_response_1.created_by.get_balance()
        recipient_2_balance = self.thread_response_2.created_by.get_balance()
        recipient_3_balance = self.thread_response_3.created_by.get_balance()

        self.assertEqual(approve_bounty_res.status_code, 200)
        # This is because of the transaction fee
        self.assertGreater(initial_user_balance + amount, user_balance)
        self.assertEqual(
            initial_recipient_1_balance + decimal.Decimal(amount / 3),
            recipient_1_balance,
        )
        self.assertEqual(
            initial_recipient_2_balance + decimal.Decimal(amount / 3),
            recipient_2_balance,
        )
        self.assertEqual(
            initial_recipient_3_balance + decimal.Decimal(amount / 3),
            recipient_3_balance,
        )

    def test_user_can_approve_partial_bounties(self):
        self.client.force_authenticate(self.user)
        amount = 600
        bounty = self.test_user_can_create_bounty(amount=amount)
        initial_user_balance = self.user.get_balance()
        initial_recipient_1_balance = self.thread_response_1.created_by.get_balance()
        initial_recipient_2_balance = self.thread_response_2.created_by.get_balance()
        initial_recipient_3_balance = self.thread_response_3.created_by.get_balance()

        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            [
                {
                    "amount": 100,
                    "object_id": self.thread_response_1.id,
                    "content_type": self.thread_response_1._meta.model_name,
                },
                {
                    "amount": 100,
                    "object_id": self.thread_response_2.id,
                    "content_type": self.thread_response_2._meta.model_name,
                },
                {
                    "amount": 100,
                    "object_id": self.thread_response_3.id,
                    "content_type": self.thread_response_3._meta.model_name,
                },
            ],
        )
        user_balance = self.user.get_balance()
        recipient_1_balance = self.thread_response_1.created_by.get_balance()
        recipient_2_balance = self.thread_response_2.created_by.get_balance()
        recipient_3_balance = self.thread_response_3.created_by.get_balance()

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(user_balance, initial_user_balance + 300)
        self.assertEqual(initial_recipient_1_balance + 100, recipient_1_balance)
        self.assertEqual(initial_recipient_2_balance + 100, recipient_2_balance)
        self.assertEqual(initial_recipient_3_balance + 100, recipient_3_balance)

    def test_user_can_approve_partial_multi_bounties(self):
        amount_1 = 600
        amount_2 = 400
        total_amount = amount_1 + amount_2
        amount_paid = 100

        # User, User_2
        bounty_1, bounty_2 = self.test_user_can_contribute_to_bounty(
            amount_1=amount_1, amount_2=amount_2
        )
        bounty_1_created_by = User.objects.get(id=bounty_1.data["created_by"]["id"])
        bounty_2_created_by = User.objects.get(id=bounty_2.data["created_by"]["id"])

        initial_bounty_1_created_by_balance = bounty_1_created_by.get_balance()
        initial_bounty_2_created_by_balance = bounty_2_created_by.get_balance()
        initial_recipient_1_balance = self.thread_response_1.created_by.get_balance()
        initial_recipient_2_balance = self.thread_response_2.created_by.get_balance()
        initial_recipient_3_balance = self.thread_response_3.created_by.get_balance()

        self.client.force_authenticate(self.user)
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/approve_bounty/",
            [
                {
                    "amount": amount_paid,
                    "object_id": self.thread_response_1.id,
                    "content_type": self.thread_response_1._meta.model_name,
                },
                {
                    "amount": amount_paid,
                    "object_id": self.thread_response_2.id,
                    "content_type": self.thread_response_2._meta.model_name,
                },
                {
                    "amount": amount_paid,
                    "object_id": self.thread_response_3.id,
                    "content_type": self.thread_response_3._meta.model_name,
                },
            ],
        )
        bounty_1_created_by_balance = bounty_1_created_by.get_balance()
        bounty_2_created_by_balance = bounty_2_created_by.get_balance()
        recipient_1_balance = self.thread_response_1.created_by.get_balance()
        recipient_2_balance = self.thread_response_2.created_by.get_balance()
        recipient_3_balance = self.thread_response_3.created_by.get_balance()
        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(initial_recipient_2_balance + amount_paid, recipient_2_balance)
        self.assertEqual(initial_recipient_3_balance + amount_paid, recipient_3_balance)
        self.assertEqual(
            bounty_1_created_by_balance,
            initial_bounty_1_created_by_balance
            + decimal.Decimal(
                (amount_1 / total_amount) * (total_amount - 3 * amount_paid)
            ),
        )

        # These 2 test results should be the same, since they are the same user
        self.assertEqual(
            initial_recipient_1_balance
            + amount_paid
            + decimal.Decimal(
                (amount_2 / total_amount) * (total_amount - 3 * amount_paid)
            ),
            recipient_1_balance,
        )
        self.assertEqual(
            bounty_2_created_by_balance,
            initial_bounty_2_created_by_balance
            + amount_paid
            + decimal.Decimal(
                (amount_2 / total_amount) * (total_amount - 3 * amount_paid)
            ),
        )

    def test_user_cant_approve_approved_bounty(self):
        self.client.force_authenticate(self.user)
        self.thread2 = create_rh_comment(created_by=self.user)

        bounty = self.test_user_can_create_bounty()

        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            [
                {
                    "amount": bounty.data["amount"],
                    "object_id": self.thread.id,
                    "content_type": self.thread._meta.model_name,
                }
            ],
        )

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(approve_bounty_res.data["amount"], bounty.data["amount"])

        approve_bounty_res_2 = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            [
                {
                    "amount": bounty.data["amount"],
                    "object_id": self.thread.id,
                    "content_type": self.thread._meta.model_name,
                }
            ],
        )

        self.assertEqual(approve_bounty_res_2.status_code, 404)

    def test_random_user_cant_approve_bounty(self):
        self.client.force_authenticate(self.user)

        bounty = self.test_user_can_create_bounty()
        self.client.force_authenticate(self.user_2)
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            [
                {
                    "amount": bounty.data["amount"],
                    "object_id": self.thread.id,
                    "content_type": self.thread._meta.model_name,
                }
            ],
        )

        self.assertEqual(approve_bounty_res.status_code, 403)

    def test_user_can_cancel_bounty(self):
        self.client.force_authenticate(self.user)

        bounty_1 = self.test_user_can_create_bounty()
        cancel_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )

        self.assertEqual(cancel_bounty_res_1.status_code, 200)

    def test_parent_user_can_cancel_multi_bounty(self):
        bounty_1, bounty_2 = self.test_user_can_contribute_to_bounty()
        self.client.force_authenticate(self.user)
        cancel_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )

        self.assertEqual(cancel_bounty_res_1.status_code, 200)

    def test_user_can_cancel_multi_bounty_with_correct_refund(self):
        self.client.force_authenticate(self.user)

        create_bounty_res_1 = self.client.post(
            "/api/bounty/",
            {
                "amount": 200,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )
        initial_user_1_balance = self.user.get_balance()
        self.assertEqual(create_bounty_res_1.status_code, 201)

        self.client.force_authenticate(self.user_2)
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": 245,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )
        initial_user_2_balance = self.user_2.get_balance()
        self.assertEqual(create_bounty_res_2.status_code, 201)

        self.client.force_authenticate(self.user_3)
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": 255,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )
        initial_user_3_balance = self.user_3.get_balance()
        self.assertEqual(create_bounty_res_2.status_code, 201)

        self.client.force_authenticate(self.user)
        cancel_bounty_res_1 = self.client.post(
            f"/api/bounty/{create_bounty_res_1.data['id']}/cancel_bounty/",
        )
        user_1_balance = self.user.get_balance()
        user_2_balance = self.user_2.get_balance()
        user_3_balance = self.user_3.get_balance()

        self.assertEqual(cancel_bounty_res_1.status_code, 200)
        self.assertEqual(initial_user_1_balance + 200, user_1_balance)
        self.assertEqual(initial_user_2_balance + 245, user_2_balance)
        self.assertEqual(initial_user_3_balance + 255, user_3_balance)

    def test_random_user_cant_cancel_bounty(self):
        self.client.force_authenticate(self.user)

        bounty_1 = self.test_user_can_create_bounty()
        self.client.force_authenticate(self.user_2)
        cancel_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )

        self.assertEqual(cancel_bounty_res_1.status_code, 403)

    def test_contribution_user_cant_cancel_multi_bounty(self):
        self.client.force_authenticate(self.user)

        bounty_1, bounty_2 = self.test_user_can_contribute_to_bounty()
        self.client.force_authenticate(self.user_2)
        cancel_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )

        self.assertEqual(cancel_bounty_res_1.status_code, 403)

    def test_random_user_cant_cancel_multi_bounty(self):
        self.client.force_authenticate(self.user)

        bounty_1, bounty_2 = self.test_user_can_contribute_to_bounty()
        self.client.force_authenticate(self.user_4)
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
        self.assertEqual(cancel_bounty_res_2.status_code, 404)

    def test_get_bounties(self):
        # Arrange
        self.client.force_authenticate(self.user)
        self.thread2 = create_rh_comment(created_by=self.user)

        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 1000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(res.status_code, 201)

        self.client.force_authenticate(self.user_2)
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.thread2._meta.model_name,
                "item_object_id": self.thread2.id,
            },
        )

        self.assertEqual(res.status_code, 201)

        # Act
        res = self.client.get("/api/bounty/")

        # Assert
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 2)

    def test_get_bounties_personalized(self):
        # Arrange
        self.client.force_authenticate(self.user)
        self.thread2 = create_rh_comment(created_by=self.user)

        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 1000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        self.assertEqual(res.status_code, 201)

        self.client.force_authenticate(self.user_2)
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.thread2._meta.model_name,
                "item_object_id": self.thread2.id,
            },
        )

        self.assertEqual(res.status_code, 201)

        # Act
        res = self.client.get("/api/bounty/?personalized=true")

        # Assert
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 2)

    def test_filter_official_account_bounties(self):
        self.client.force_authenticate(self.rh_official)

        # Create bounty
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
            },
        )

        created_bounty_id = res.data["id"]

        res = self.client.get(
            "/api/bounty/",
            {
                "status": "OPEN",
                "bounty_type": ["RESEARCHHUB"],
            },
        )

        self.assertEqual(created_bounty_id, res.data["results"][0]["id"])

    def test_filter_review_bounty_type(self):
        self.client.force_authenticate(self.rh_official)

        # Create bounty
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
                "bounty_type": Bounty.Type.REVIEW,
            },
        )

        created_bounty_id = res.data["id"]

        res = self.client.get(
            "/api/bounty/",
            {
                "status": "OPEN",
                "bounty_type": [Bounty.Type.REVIEW],
            },
        )

        self.assertEqual(created_bounty_id, res.data["results"][0]["id"])

    def test_filter_answer_bounty_type(self):
        self.client.force_authenticate(self.rh_official)

        # Create bounty
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
                "bounty_type": Bounty.Type.ANSWER,
            },
        )

        created_bounty_id = res.data["id"]

        res = self.client.get(
            "/api/bounty/",
            {
                "status": "OPEN",
                "bounty_type": [Bounty.Type.ANSWER],
            },
        )

        self.assertEqual(created_bounty_id, res.data["results"][0]["id"])

    def test_filter_other_bounty_type(self):
        self.client.force_authenticate(self.rh_official)

        # Create bounty
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
                "bounty_type": Bounty.Type.OTHER,
            },
        )

        created_bounty_id = res.data["id"]

        res = self.client.get(
            "/api/bounty/",
            {
                "status": "OPEN",
                "bounty_type": [Bounty.Type.OTHER],
            },
        )

        self.assertEqual(created_bounty_id, res.data["results"][0]["id"])

    def test_filter_hub_specific_bounties_type(self):

        # Arrange: Create hub and add it to the paper
        paper = create_paper()
        hub = Hub.objects.create(
            name="testHub",
        )

        paper.unified_document.hubs.add(hub)
        self.thread = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.client.force_authenticate(self.rh_official)

        # Create bounty
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
                "bounty_type": Bounty.Type.OTHER,
            },
        )

        created_bounty_id = res.data["id"]

        res = self.client.get(
            "/api/bounty/",
            {
                "status": "OPEN",
                "hub_ids": [hub.id],
            },
        )

        self.assertEqual(created_bounty_id, res.data["results"][0]["id"])

    def test_sort_bounties_by_expiring_soon(self):
        # Arrange
        paper = create_paper()
        hub = Hub.objects.create(
            name="testHub",
        )

        paper.unified_document.hubs.add(hub)
        self.thread = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.thread2 = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.client.force_authenticate(self.rh_official)

        # Create bounty 1
        self.client.post(
            "/api/bounty/",
            {
                "amount": 101,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
                "bounty_type": Bounty.Type.OTHER,
                "expiration_date": "2040-01-01T00:00:00Z",
            },
        )

        # Create bounty 2 (expiring sooner)
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 102,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread2.id,
                "bounty_type": Bounty.Type.OTHER,
                "expiration_date": "2030-01-01T00:00:00Z",
            },
        )

        expiring_soon_bounty_id = res.data["id"]

        res = self.client.get(
            "/api/bounty/",
            {"status": "OPEN", "sort": "expiration_date"},
        )

        # Assert
        self.assertEqual(expiring_soon_bounty_id, res.data["results"][0]["id"])

    def test_sort_bounties_by_amount(self):
        # Arrange
        paper = create_paper()
        hub = Hub.objects.create(
            name="testHub",
        )

        paper.unified_document.hubs.add(hub)
        self.thread = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.thread2 = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.client.force_authenticate(self.rh_official)

        # Create bounty 1 (larger amount)
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 1000,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
                "bounty_type": Bounty.Type.OTHER,
                "expiration_date": "2040-01-01T00:00:00Z",
            },
        )

        larger_amount_id = res.data["id"]

        # Create bounty 2
        self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread2.id,
                "bounty_type": Bounty.Type.OTHER,
                "expiration_date": "2030-01-01T00:00:00Z",
            },
        )

        res = self.client.get(
            "/api/bounty/",
            {"status": "OPEN", "sort": "-total_amount"},
        )

        # Assert
        self.assertEqual(res.data["results"][0]["id"], larger_amount_id)

    def test_user_vote_included_in_bounty_response(self):
        """Test that user's vote is correctly included in bounty serialization"""
        # Arrange - create a bounty for the thread (which already has votes in setup)
        self.client.force_authenticate(self.user)

        # Create a bounty
        self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.thread._meta.model_name,
                "item_object_id": self.thread.id,
                "bounty_type": Bounty.Type.OTHER,
                "expiration_date": "2040-01-01T00:00:00Z",
            },
        )

        for user in [self.user, self.moderator]:
            # Act - Retrieve the bounty detail
            bounty_res = self.client.get(
                "/api/bounty/",
            )

            # Assert - Verify the user_vote field reflects the correct vote
            self.assertIsNotNone(bounty_res.data["results"][0]["user_vote"])
            self.assertEqual(
                bounty_res.data["results"][0]["user_vote"]["vote_type"], Vote.UPVOTE
            )
