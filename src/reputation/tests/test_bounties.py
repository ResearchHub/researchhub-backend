import decimal
import time
from datetime import datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.utils import timezone
from rest_framework.test import APITestCase

from discussion.models import Vote
from hub.models import Hub
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Bounty, BountyFee, BountySolution, Distribution
from researchhub_comment.tests.helpers import create_rh_comment
from user.models import User
from user.related_models.user_model import FOUNDATION_REVENUE_EMAIL
from user.tests.helpers import create_moderator, create_random_default_user, create_user


class BountyViewTests(APITestCase):
    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.user = create_random_default_user("bounty_user")
        self.user_2 = create_random_default_user("bounty_user_2")
        self.user_3 = create_random_default_user("bounty_user_3")
        self.user_4 = create_random_default_user("bounty_user_4")
        self.user_5 = create_random_default_user("bounty_user_5")
        self.recipient = create_random_default_user("bounty_recipient")
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")

        self.rh_official = create_random_default_user("rh_official")
        self.rh_official.is_official_account = True
        self.rh_official.save()

        self.comment = create_rh_comment(created_by=self.recipient)
        self.child_comment_1 = create_rh_comment(
            created_by=self.user_5, parent=self.comment
        )
        self.child_comment_2 = create_rh_comment(
            created_by=self.user_3, parent=self.comment
        )
        self.child_comment_3 = create_rh_comment(
            created_by=self.user_4, parent=self.comment
        )
        self.comment.score = 1
        self.comment.save()
        self.hub = create_hub()
        self.bountyFee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        self._create_vote(self.user, self.comment, Vote.UPVOTE)
        self._create_vote(self.user_2, self.comment, Vote.UPVOTE)
        self._create_vote(self.user_3, self.comment, Vote.DOWNVOTE)

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

        distributor = Distributor(
            distribution, self.user_5, self.user_5, time.time(), self.user_5
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        self.assertEqual(create_bounty_res_1.status_code, 201)

        self.client.force_authenticate(self.user_2)
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": amount_2,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)

    def test_user_can_create_long_decimal_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 123.45679001,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)

    def test_user_cant_create_negative_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": -1234.123,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": "--100",
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        create_bounty_res_3 = self.client.post(
            "/api/bounty/",
            {
                "amount": "0xFFA",
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 400)

    def test_user_cant_create_high_bounty(self):
        self.client.force_authenticate(self.user)

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 10000000,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                    "object_id": self.comment.id,
                    "content_type": self.comment._meta.model_name,
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
                    "object_id": self.comment.id,
                    "content_type": self.comment._meta.model_name,
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
                    "object_id": self.comment.id,
                    "content_type": self.comment._meta.model_name,
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
        initial_recipient_1_balance = self.child_comment_1.created_by.get_balance()
        initial_recipient_2_balance = self.child_comment_2.created_by.get_balance()
        initial_recipient_3_balance = self.child_comment_3.created_by.get_balance()
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            [
                {
                    "amount": amount / 3,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                },
                {
                    "amount": amount / 3,
                    "object_id": self.child_comment_2.id,
                    "content_type": self.child_comment_2._meta.model_name,
                },
                {
                    "amount": amount / 3,
                    "object_id": self.child_comment_3.id,
                    "content_type": self.child_comment_3._meta.model_name,
                },
            ],
        )

        user_balance = self.user.get_balance()
        recipient_1_balance = self.child_comment_1.created_by.get_balance()
        recipient_2_balance = self.child_comment_2.created_by.get_balance()
        recipient_3_balance = self.child_comment_3.created_by.get_balance()

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
        initial_recipient_1_balance = self.child_comment_1.created_by.get_balance()
        initial_recipient_2_balance = self.child_comment_2.created_by.get_balance()
        initial_recipient_3_balance = self.child_comment_3.created_by.get_balance()

        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            [
                {
                    "amount": 100,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                },
                {
                    "amount": 100,
                    "object_id": self.child_comment_2.id,
                    "content_type": self.child_comment_2._meta.model_name,
                },
                {
                    "amount": 100,
                    "object_id": self.child_comment_3.id,
                    "content_type": self.child_comment_3._meta.model_name,
                },
            ],
        )
        user_balance = self.user.get_balance()
        recipient_1_balance = self.child_comment_1.created_by.get_balance()
        recipient_2_balance = self.child_comment_2.created_by.get_balance()
        recipient_3_balance = self.child_comment_3.created_by.get_balance()

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(user_balance, initial_user_balance)
        self.assertEqual(initial_recipient_1_balance + 100, recipient_1_balance)
        self.assertEqual(initial_recipient_2_balance + 100, recipient_2_balance)
        self.assertEqual(initial_recipient_3_balance + 100, recipient_3_balance)
        self.assertEqual(
            decimal.Decimal(approve_bounty_res.data["amount_remaining"]), 300.00
        )

    def test_user_can_approve_partial_multi_bounties(self):
        amount_1 = 600
        amount_2 = 400
        amount_paid = 100

        # User, User_2
        bounty_1, bounty_2 = self.test_user_can_contribute_to_bounty(
            amount_1=amount_1, amount_2=amount_2
        )
        bounty_1_created_by = User.objects.get(id=bounty_1.data["created_by"]["id"])
        bounty_2_created_by = User.objects.get(id=bounty_2.data["created_by"]["id"])

        initial_bounty_1_created_by_balance = bounty_1_created_by.get_balance()
        initial_bounty_2_created_by_balance = bounty_2_created_by.get_balance()
        initial_recipient_1_balance = self.child_comment_1.created_by.get_balance()
        initial_recipient_2_balance = self.child_comment_2.created_by.get_balance()
        initial_recipient_3_balance = self.child_comment_3.created_by.get_balance()

        self.client.force_authenticate(self.user)
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/approve_bounty/",
            [
                {
                    "amount": amount_paid,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                },
                {
                    "amount": amount_paid,
                    "object_id": self.child_comment_2.id,
                    "content_type": self.child_comment_2._meta.model_name,
                },
                {
                    "amount": amount_paid,
                    "object_id": self.child_comment_3.id,
                    "content_type": self.child_comment_3._meta.model_name,
                },
            ],
        )
        bounty_1_created_by_balance = bounty_1_created_by.get_balance()
        bounty_2_created_by_balance = bounty_2_created_by.get_balance()
        recipient_1_balance = self.child_comment_1.created_by.get_balance()
        recipient_2_balance = self.child_comment_2.created_by.get_balance()
        recipient_3_balance = self.child_comment_3.created_by.get_balance()
        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(
            recipient_1_balance,
            initial_recipient_1_balance + decimal.Decimal(amount_paid),
        )
        self.assertEqual(
            recipient_2_balance,
            initial_recipient_2_balance + decimal.Decimal(amount_paid),
        )
        self.assertEqual(
            recipient_3_balance,
            initial_recipient_3_balance + decimal.Decimal(amount_paid),
        )

        # Check contributor balances (Should not change since bounty remains open)
        # No refund happens when bounty is partially awarded and remains open
        self.assertEqual(
            bounty_1_created_by_balance, initial_bounty_1_created_by_balance
        )
        self.assertEqual(
            bounty_2_created_by_balance, initial_bounty_2_created_by_balance
        )

    def test_user_cant_approve_approved_bounty(self):
        self.client.force_authenticate(self.user)
        self.comment2 = create_rh_comment(created_by=self.user)

        bounty = self.test_user_can_create_bounty()

        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
            [
                {
                    "amount": bounty.data["amount"],
                    "object_id": self.comment.id,
                    "content_type": self.comment._meta.model_name,
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
                    "object_id": self.comment.id,
                    "content_type": self.comment._meta.model_name,
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
                    "object_id": self.comment.id,
                    "content_type": self.comment._meta.model_name,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        initial_user_1_balance = self.user.get_balance()
        self.assertEqual(create_bounty_res_1.status_code, 201)

        self.client.force_authenticate(self.user_2)
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": 245,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        initial_user_2_balance = self.user_2.get_balance()
        self.assertEqual(create_bounty_res_2.status_code, 201)

        self.client.force_authenticate(self.user_3)
        create_bounty_res_2 = self.client.post(
            "/api/bounty/",
            {
                "amount": 255,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
        self.comment2 = create_rh_comment(created_by=self.user)

        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 1000,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        self.assertEqual(res.status_code, 201)

        self.client.force_authenticate(self.user_2)
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.comment2._meta.model_name,
                "item_object_id": self.comment2.id,
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
        self.comment2 = create_rh_comment(created_by=self.user)

        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 1000,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        self.assertEqual(res.status_code, 201)

        self.client.force_authenticate(self.user_2)
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.comment2._meta.model_name,
                "item_object_id": self.comment2.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
        self.comment = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.client.force_authenticate(self.rh_official)

        # Create bounty
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 2000,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
        self.comment = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.comment2 = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.client.force_authenticate(self.rh_official)

        # Create bounty 1
        self.client.post(
            "/api/bounty/",
            {
                "amount": 101,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
                "bounty_type": Bounty.Type.OTHER,
                "expiration_date": "2040-01-01T00:00:00Z",
            },
        )

        # Create bounty 2 (expiring sooner)
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 102,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment2.id,
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
        self.comment = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.comment2 = create_rh_comment(created_by=self.rh_official, paper=paper)
        self.client.force_authenticate(self.rh_official)

        # Create bounty 1 (larger amount)
        res = self.client.post(
            "/api/bounty/",
            {
                "amount": 1000,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
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
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment2.id,
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
        # Arrange
        self.client.force_authenticate(self.user)

        self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
                "bounty_type": Bounty.Type.OTHER,
                "expiration_date": "2040-01-01T00:00:00Z",
            },
        )

        # Act
        bounty_res = self.client.get(
            "/api/bounty/",
        )

        # Assert
        self.assertIsNotNone(bounty_res.data["results"][0]["user_vote"])
        self.assertEqual(
            bounty_res.data["results"][0]["user_vote"]["vote_type"], Vote.UPVOTE
        )

    def test_moderator_user_vote_not_included_in_bounty_response(self):
        """Test that moderator's user_vote is not included in bounty response"""
        # Arrange
        self.client.force_authenticate(self.user)

        self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
                "bounty_type": Bounty.Type.OTHER,
                "expiration_date": "2040-01-01T00:00:00Z",
            },
        )

        # Act
        self.client.force_authenticate(self.moderator)
        bounty_res = self.client.get(
            "/api/bounty/",
        )

        # Assert
        self.assertIsNone(bounty_res.data["results"][0]["user_vote"])

    def test_metrics_included_in_bounty_response(self):
        """Test that metrics are correctly included in bounty response"""
        # Arrange
        self.client.force_authenticate(self.user)

        comment_bounty_response = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
                "bounty_type": Bounty.Type.OTHER,
                "expiration_date": "2040-01-01T00:00:00Z",
            },
        )

        self.assertEqual(comment_bounty_response.status_code, 201)

        # Test: Verify comment bounty metrics
        comment_bounty_response = self.client.get(
            "/api/bounty/",
        )
        self.assertEqual(comment_bounty_response.status_code, 200)
        self.assertIn("metrics", comment_bounty_response.data["results"][0])

        # The metrics should contain votes count
        # (the comment has 2 upvotes, 1 downvote = score of 1)
        self.assertEqual(
            comment_bounty_response.data["results"][0]["metrics"]["votes"], 1
        )
        # The metrics should contain replies count (the comment has 3 replies)
        self.assertEqual(
            comment_bounty_response.data["results"][0]["metrics"]["replies"], 3
        )

    def test_user_can_approve_full_amount_to_multiple_solutions(self):
        self.client.force_authenticate(self.user)
        amount = 600
        bounty_res = self.test_user_can_create_bounty(amount=amount)
        bounty_id = bounty_res.data["id"]
        bounty = Bounty.objects.get(id=bounty_id)

        initial_user_balance = self.user.get_balance()
        initial_recipient_1_balance = self.child_comment_1.created_by.get_balance()
        initial_recipient_2_balance = self.child_comment_2.created_by.get_balance()

        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": amount / 2,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                },
                {
                    "amount": amount / 2,
                    "object_id": self.child_comment_2.id,
                    "content_type": self.child_comment_2._meta.model_name,
                },
            ],
        )

        user_balance = self.user.get_balance()
        recipient_1_balance = self.child_comment_1.created_by.get_balance()
        recipient_2_balance = self.child_comment_2.created_by.get_balance()
        bounty.refresh_from_db()

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(bounty.status, Bounty.CLOSED)
        total_awarded = (
            bounty.solutions.filter(status=BountySolution.Status.AWARDED).aggregate(
                total=Sum("awarded_amount")
            )["total"]
            or 0
        )
        self.assertEqual(total_awarded, decimal.Decimal(amount))

        # Check balances (consider fee)
        # User balance should not change as they paid upfront
        self.assertEqual(user_balance, initial_user_balance)

        self.assertEqual(
            recipient_1_balance,
            initial_recipient_1_balance + decimal.Decimal(amount / 2),
        )
        self.assertEqual(
            recipient_2_balance,
            initial_recipient_2_balance + decimal.Decimal(amount / 2),
        )
        self.assertEqual(
            approve_bounty_res.data["awarded_solutions"][0]["status"], "AWARDED"
        )
        self.assertEqual(
            approve_bounty_res.data["awarded_solutions"][1]["status"], "AWARDED"
        )
        self.assertEqual(
            decimal.Decimal(
                approve_bounty_res.data["awarded_solutions"][0]["awarded_amount"]
            ),
            decimal.Decimal(amount / 2),
        )
        self.assertEqual(
            decimal.Decimal(
                approve_bounty_res.data["awarded_solutions"][1]["awarded_amount"]
            ),
            decimal.Decimal(amount / 2),
        )

    def test_user_can_approve_partial_amount_to_multiple_solutions(self):
        self.client.force_authenticate(self.user)
        amount = 600
        partial_award_amount = 100
        expiration_time = timezone.now() + timedelta(days=30)
        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": amount,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
                "expiration_date": expiration_time.isoformat(),
            },
        )
        self.assertEqual(create_bounty_res.status_code, 201)
        bounty_id = create_bounty_res.data["id"]
        bounty = Bounty.objects.get(id=bounty_id)

        initial_user_balance = self.user.get_balance()
        initial_recipient_1_balance = self.child_comment_1.created_by.get_balance()
        initial_recipient_2_balance = self.child_comment_2.created_by.get_balance()

        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": partial_award_amount,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                },
                {
                    "amount": partial_award_amount,
                    "object_id": self.child_comment_2.id,
                    "content_type": self.child_comment_2._meta.model_name,
                },
            ],
        )

        user_balance = self.user.get_balance()
        recipient_1_balance = self.child_comment_1.created_by.get_balance()
        recipient_2_balance = self.child_comment_2.created_by.get_balance()
        bounty.refresh_from_db()

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(
            bounty.status, Bounty.OPEN
        )  # Bounty should remain OPEN after partial award
        # Check that amount_remaining is correct
        self.assertEqual(
            decimal.Decimal(approve_bounty_res.data["amount_remaining"]),
            decimal.Decimal(amount - 2 * partial_award_amount),
        )
        total_awarded = (
            bounty.solutions.filter(status=BountySolution.Status.AWARDED).aggregate(
                total=Sum("awarded_amount")
            )["total"]
            or 0
        )
        self.assertEqual(total_awarded, decimal.Decimal(2 * partial_award_amount))

        # Check balances (no refund since bounty is still open)
        # User balance should not change
        self.assertEqual(user_balance, initial_user_balance)

        self.assertEqual(
            recipient_1_balance,
            initial_recipient_1_balance + decimal.Decimal(partial_award_amount),
        )
        self.assertEqual(
            recipient_2_balance,
            initial_recipient_2_balance + decimal.Decimal(partial_award_amount),
        )
        self.assertEqual(
            approve_bounty_res.data["awarded_solutions"][0]["status"], "AWARDED"
        )
        self.assertEqual(
            approve_bounty_res.data["awarded_solutions"][1]["status"], "AWARDED"
        )
        self.assertEqual(
            decimal.Decimal(
                approve_bounty_res.data["awarded_solutions"][0]["awarded_amount"]
            ),
            decimal.Decimal(partial_award_amount),
        )
        self.assertEqual(
            decimal.Decimal(
                approve_bounty_res.data["awarded_solutions"][1]["awarded_amount"]
            ),
            decimal.Decimal(partial_award_amount),
        )

    def test_approve_multiple_solutions_exceeding_bounty_amount_fails(self):
        self.client.force_authenticate(self.user)
        amount = 100
        bounty_res = self.test_user_can_create_bounty(amount=amount)
        bounty_id = bounty_res.data["id"]

        initial_user_balance = self.user.get_balance()
        initial_recipient_1_balance = self.child_comment_1.created_by.get_balance()
        initial_recipient_2_balance = self.child_comment_2.created_by.get_balance()

        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": amount,  # Award full amount to first solution
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                },
                {
                    "amount": 1,  # Try to award more to second solution
                    "object_id": self.child_comment_2.id,
                    "content_type": self.child_comment_2._meta.model_name,
                },
            ],
        )

        user_balance = self.user.get_balance()
        recipient_1_balance = self.child_comment_1.created_by.get_balance()
        recipient_2_balance = self.child_comment_2.created_by.get_balance()

        self.assertEqual(approve_bounty_res.status_code, 400)  # Expecting Bad Request

        # Ensure balances haven't changed
        self.assertEqual(user_balance, initial_user_balance)
        self.assertEqual(recipient_1_balance, initial_recipient_1_balance)
        self.assertEqual(recipient_2_balance, initial_recipient_2_balance)

    def test_approve_multiple_solutions_with_non_existent_solution_fails(self):
        self.client.force_authenticate(self.user)
        amount = 100
        bounty_res = self.test_user_can_create_bounty(amount=amount)
        bounty_id = bounty_res.data["id"]

        initial_user_balance = self.user.get_balance()
        initial_recipient_1_balance = self.child_comment_1.created_by.get_balance()

        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": amount / 2,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                },
                {
                    "amount": amount / 2,
                    "object_id": 999999,  # Non-existent comment ID
                    # Content type doesn't matter here
                    "content_type": self.child_comment_1._meta.model_name,
                },
            ],
        )

        user_balance = self.user.get_balance()
        recipient_1_balance = self.child_comment_1.created_by.get_balance()

        self.assertEqual(approve_bounty_res.status_code, 404)

        # Ensure balances haven't changed
        self.assertEqual(user_balance, initial_user_balance)
        self.assertEqual(recipient_1_balance, initial_recipient_1_balance)

    def test_approve_multiple_solutions_for_multi_contributor_bounty(self):
        amount_1 = 600
        amount_2 = 400
        award_amount_1 = 200
        award_amount_2 = 300
        total_award = award_amount_1 + award_amount_2

        # User1 creates bounty 1, User2 creates bounty 2 (contributes)
        bounty_1_res, bounty_2_res = self.test_user_can_contribute_to_bounty(
            amount_1=amount_1, amount_2=amount_2
        )
        bounty_id = bounty_1_res.data["id"]  # Use the parent bounty ID
        bounty = Bounty.objects.get(id=bounty_id)

        user_1 = User.objects.get(id=bounty_1_res.data["created_by"]["id"])
        user_2 = User.objects.get(id=bounty_2_res.data["created_by"]["id"])
        recipient_1 = self.child_comment_1.created_by
        recipient_2 = self.child_comment_2.created_by

        initial_user_1_balance = user_1.get_balance()
        initial_user_2_balance = user_2.get_balance()
        initial_recipient_1_balance = recipient_1.get_balance()
        initial_recipient_2_balance = recipient_2.get_balance()

        # Original creator (user_1) approves
        self.client.force_authenticate(user_1)
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": award_amount_1,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                },
                {
                    "amount": award_amount_2,
                    "object_id": self.child_comment_2.id,
                    "content_type": self.child_comment_2._meta.model_name,
                },
            ],
        )

        user_1_balance = user_1.get_balance()
        user_2_balance = user_2.get_balance()
        recipient_1_balance = recipient_1.get_balance()
        recipient_2_balance = recipient_2.get_balance()
        bounty.refresh_from_db()

        self.assertEqual(approve_bounty_res.status_code, 200)
        self.assertEqual(
            bounty.status, Bounty.OPEN
        )  # Bounty remains open after partial award
        total_awarded = (
            bounty.solutions.filter(status=BountySolution.Status.AWARDED).aggregate(
                total=Sum("awarded_amount")
            )["total"]
            or 0
        )
        self.assertEqual(total_awarded, decimal.Decimal(total_award))

        # Check recipient balances
        self.assertEqual(
            recipient_1_balance,
            initial_recipient_1_balance + decimal.Decimal(award_amount_1),
        )
        self.assertEqual(
            recipient_2_balance,
            initial_recipient_2_balance + decimal.Decimal(award_amount_2),
        )

        # Check contributor balances (no refunds since bounty remains open)
        # Balances should not change when bounty is partially awarded
        self.assertEqual(user_1_balance, initial_user_1_balance)
        self.assertEqual(user_2_balance, initial_user_2_balance)

    def test_hubs_endpoint_returns_hubs_with_bounties(self):
        """Ensure /api/bounty/hubs/ returns hubs linked to open bounties."""
        # Arrange: create a hub linked paper and bounty
        paper = create_paper()
        paper.unified_document.hubs.add(self.hub)
        comment = create_rh_comment(created_by=self.user, paper=paper)
        self.client.force_authenticate(self.user)
        self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": comment._meta.model_name,
                "item_object_id": comment.id,
            },
        )

        # Act
        response = self.client.get("/api/bounty/hubs/")

        # Assert
        self.assertEqual(response.status_code, 200)
        hub_ids = [hub["id"] for hub in response.data]
        self.assertIn(self.hub.id, hub_ids)

    def test_hubs_endpoint_excludes_hubs_without_bounties(self):
        """Hubs without open bounties should not be returned by the endpoint."""
        # Arrange: create another hub without bounty
        from hub.tests.helpers import create_hub as test_create_hub

        unused_hub = test_create_hub(name="Unused Hub")

        # Ensure the unused hub has no bounty

        # Act
        response = self.client.get("/api/bounty/hubs/")

        # Assert
        self.assertEqual(response.status_code, 200)
        hub_ids = [hub["id"] for hub in response.data]
        self.assertNotIn(unused_hub.id, hub_ids)

    def test_bounty_remains_open_after_partial_award(self):
        """Test that bounty remains open when partially awarded"""
        self.client.force_authenticate(self.user)
        amount = 1000
        partial_amount = 300

        # Create bounty
        bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": amount,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Partially award the bounty
        approve_res = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": partial_amount,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                }
            ],
        )

        self.assertEqual(approve_res.status_code, 200)
        self.assertEqual(approve_res.data["status"], Bounty.OPEN)
        self.assertEqual(
            decimal.Decimal(approve_res.data["amount_remaining"]),
            decimal.Decimal(amount - partial_amount),
        )
        self.assertIn("remaining open for future awards", approve_res.data["message"])

        # Verify bounty is still open in database
        bounty = Bounty.objects.get(id=bounty_id)
        self.assertEqual(bounty.status, Bounty.OPEN)
        self.assertEqual(
            bounty.escrow.amount_holding, decimal.Decimal(amount - partial_amount)
        )

    def test_bounty_closes_when_fully_depleted(self):
        """Test that bounty closes only when escrow is fully depleted"""
        self.client.force_authenticate(self.user)
        amount = 1000

        # Create bounty
        bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": amount,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # First partial award
        approve_res_1 = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": 400,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                }
            ],
        )
        self.assertEqual(approve_res_1.status_code, 200)
        self.assertEqual(approve_res_1.data["status"], Bounty.OPEN)
        self.assertEqual(decimal.Decimal(approve_res_1.data["amount_remaining"]), 600)

        # Second partial award
        approve_res_2 = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": 300,
                    "object_id": self.child_comment_2.id,
                    "content_type": self.child_comment_2._meta.model_name,
                }
            ],
        )
        self.assertEqual(approve_res_2.status_code, 200)
        self.assertEqual(approve_res_2.data["status"], Bounty.OPEN)
        self.assertEqual(decimal.Decimal(approve_res_2.data["amount_remaining"]), 300)

        # Final award that depletes the bounty
        approve_res_3 = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": 300,
                    "object_id": self.child_comment_3.id,
                    "content_type": self.child_comment_3._meta.model_name,
                }
            ],
        )
        self.assertEqual(approve_res_3.status_code, 200)
        self.assertEqual(approve_res_3.data["status"], Bounty.CLOSED)
        self.assertEqual(decimal.Decimal(approve_res_3.data["amount_remaining"]), 0)
        self.assertIn("successfully closed", approve_res_3.data["message"])

        # Verify bounty is closed in database
        bounty = Bounty.objects.get(id=bounty_id)
        self.assertEqual(bounty.status, Bounty.CLOSED)
        self.assertEqual(bounty.escrow.amount_holding, 0)

    def test_bounty_dao_fee_goes_to_community_revenue_account(self):
        community_revenue_user, _ = User.objects.get_or_create(
            email=FOUNDATION_REVENUE_EMAIL
        )
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(response.status_code, 201)
        dao_fee_distribution = Distribution.objects.filter(
            distribution_type="BOUNTY_DAO_FEE"
        ).latest("created_date")
        self.assertEqual(dao_fee_distribution.recipient, community_revenue_user)
