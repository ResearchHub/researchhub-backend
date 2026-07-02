import decimal
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.utils import timezone
from rest_framework.test import APITestCase

from discussion.models import Vote
from hub.models import Hub
from hub.tests.helpers import create_hub
from notification.models import Notification
from paper.tests.helpers import create_paper
from reputation.constants.bounty import ASSESSMENT_PERIOD_DAYS
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Bounty, BountyFee, BountySolution, Distribution
from reputation.tasks import check_open_bounties
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_comment.tests.helpers import create_rh_comment
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User
from user.related_models.user_model import FOUNDATION_EMAIL, FOUNDATION_REVENUE_EMAIL
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
        self.foundation = create_user(email=FOUNDATION_EMAIL)
        self.foundation.is_official_account = True
        self.foundation.save(update_fields=["is_official_account"])

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
        self.hub = create_hub(namespace=Hub.Namespace.SUBCATEGORY)
        self.bountyFee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        self._create_vote(self.user, self.comment, Vote.UPVOTE)
        self._create_vote(self.user_2, self.comment, Vote.UPVOTE)
        self._create_vote(self.user_3, self.comment, Vote.DOWNVOTE)

        self._authenticate_bounty_manager()

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

        distributor = Distributor(
            distribution,
            self.foundation,
            self.foundation,
            time.time(),
            self.foundation,
        )
        distributor.distribute()

        distributor = Distributor(
            distribution,
            self.moderator,
            self.moderator,
            time.time(),
            self.moderator,
        )
        distributor.distribute()

    def _authenticate_bounty_manager(self, user=None):
        self.client.force_authenticate(user or self.foundation)

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

    def test_user_cannot_create_bounty(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_moderator_can_create_bounty(self):
        self._authenticate_bounty_manager(self.moderator)
        response = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(response.status_code, 201)

    def test_other_moderator_cannot_approve_bounty_they_did_not_create(self):
        self._authenticate_bounty_manager(self.moderator)
        create_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(create_res.status_code, 201)

        other_moderator = create_random_default_user("other_mod_bounty", moderator=True)
        self.client.force_authenticate(other_moderator)
        approve_res = self.client.post(
            f"/api/bounty/{create_res.data['id']}/approve_bounty/",
            [
                {
                    "amount": 50,
                    "object_id": self.comment.id,
                    "content_type": self.comment._meta.model_name,
                }
            ],
        )
        self.assertEqual(approve_res.status_code, 403)

    def test_backing_existing_bounty_not_allowed(self):
        self._authenticate_bounty_manager()
        first_response = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(first_response.status_code, 201)

        second_response = self.client.post(
            "/api/bounty/",
            {
                "amount": 200,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(second_response.status_code, 400)
        self.assertIn(
            "Contributions to existing bounties", second_response.data["detail"]
        )

    def test_user_can_create_bounty(self, amount=100):
        self._authenticate_bounty_manager()

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

    def test_user_can_create_larger_bounty(self):
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        # Verify assessment_end_date is included in response
        # (should be None for OPEN bounties)
        self.assertIn("assessment_end_date", create_bounty_res.data)
        self.assertIsNone(create_bounty_res.data["assessment_end_date"])

    def test_assessment_end_date_included_in_create_response(self):
        """Test that assessment_end_date is included in bounty create response"""
        self._authenticate_bounty_manager()

        create_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        self.assertEqual(create_bounty_res.status_code, 201)
        self.assertIn("assessment_end_date", create_bounty_res.data)
        # For OPEN bounties, assessment_end_date should be None
        self.assertIsNone(create_bounty_res.data["assessment_end_date"])

    def test_user_cant_create_invalid_bounty(self):
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        # Verify assessment_end_date is included in approve_bounty response
        self.assertIn("assessment_end_date", approve_bounty_res.data)

    def test_assessment_end_date_included_in_approve_bounty_response(self):
        """Test that assessment_end_date is included in approve_bounty response"""
        self._authenticate_bounty_manager()

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
        self.assertIn("assessment_end_date", approve_bounty_res.data)

    def test_user_can_approve_partial_bounty(self):
        self._authenticate_bounty_manager()

        initial_foundation_balance = self.foundation.get_balance()
        initial_recipient_balance = self.recipient.get_balance()
        initial_child_1_balance = self.child_comment_1.created_by.get_balance()
        bounty_1 = self.test_user_can_create_bounty()
        half_amount = decimal.Decimal(bounty_1.data["amount"]) / 2
        approve_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/approve_bounty/",
            [
                {
                    "amount": half_amount,
                    "object_id": self.comment.id,
                    "content_type": self.comment._meta.model_name,
                }
            ],
        )

        self.assertEqual(approve_bounty_res_1.status_code, 200)
        self.assertEqual(approve_bounty_res_1.data["amount"], bounty_1.data["amount"])

        approve_bounty_res_2 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/approve_bounty/",
            [
                {
                    "amount": half_amount,
                    "object_id": self.child_comment_1.id,
                    "content_type": self.child_comment_1._meta.model_name,
                }
            ],
        )
        foundation_balance = self.foundation.get_balance()
        recipient_balance = self.recipient.get_balance()
        child_1_balance = self.child_comment_1.created_by.get_balance()

        self.assertEqual(approve_bounty_res_2.status_code, 200)
        self.assertGreater(recipient_balance, initial_recipient_balance)
        self.assertGreater(child_1_balance, initial_child_1_balance)
        self.assertGreater(initial_foundation_balance, foundation_balance)

    def test_user_can_approve_full_multi_bounties(self):
        self._authenticate_bounty_manager()
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
        self._authenticate_bounty_manager()
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
        amount = 1000
        amount_paid = 100

        bounty = self.test_user_can_create_bounty(amount=amount)
        initial_foundation_balance = self.foundation.get_balance()
        initial_recipient_1_balance = self.child_comment_1.created_by.get_balance()
        initial_recipient_2_balance = self.child_comment_2.created_by.get_balance()
        initial_recipient_3_balance = self.child_comment_3.created_by.get_balance()

        self._authenticate_bounty_manager()
        approve_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/approve_bounty/",
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
        foundation_balance = self.foundation.get_balance()
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

        self.assertEqual(foundation_balance, initial_foundation_balance)

    def test_user_cant_approve_approved_bounty(self):
        self._authenticate_bounty_manager()
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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

        bounty_1 = self.test_user_can_create_bounty()
        cancel_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )

        self.assertEqual(cancel_bounty_res_1.status_code, 200)
        # Verify assessment_end_date is included in cancel_bounty response
        self.assertIn("assessment_end_date", cancel_bounty_res_1.data)

    def test_assessment_end_date_included_in_cancel_bounty_response(self):
        """Test that assessment_end_date is included in cancel_bounty response"""
        self._authenticate_bounty_manager()

        bounty = self.test_user_can_create_bounty()
        cancel_bounty_res = self.client.post(
            f"/api/bounty/{bounty.data['id']}/cancel_bounty/",
        )

        self.assertEqual(cancel_bounty_res.status_code, 200)
        self.assertIn("assessment_end_date", cancel_bounty_res.data)

    def test_random_user_cant_cancel_bounty(self):
        self._authenticate_bounty_manager()

        bounty_1 = self.test_user_can_create_bounty()
        self.client.force_authenticate(self.user_2)
        cancel_bounty_res_1 = self.client.post(
            f"/api/bounty/{bounty_1.data['id']}/cancel_bounty/",
        )

        self.assertEqual(cancel_bounty_res_1.status_code, 403)

    def test_user_cant_cancel_cancelled_bounty(self):
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()
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
        # Verify assessment_end_date is included in list response
        for bounty in res.data["results"]:
            self.assertIn("assessment_end_date", bounty)

    def test_assessment_end_date_included_in_list_response(self):
        """Test that assessment_end_date is included in bounty list response"""
        self._authenticate_bounty_manager()

        # Create a bounty
        self.client.post(
            "/api/bounty/",
            {
                "amount": 1000,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        # Get bounties
        res = self.client.get("/api/bounty/")

        self.assertEqual(res.status_code, 200)
        self.assertGreater(len(res.data["results"]), 0)
        # Verify assessment_end_date is included in response
        self.assertIn("assessment_end_date", res.data["results"][0])

    def test_get_bounties_personalized(self):
        # Arrange
        self._authenticate_bounty_manager()
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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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
        self._authenticate_bounty_manager()

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

        # Act — vote on comment is from self.user; list as that user for user_vote
        self.client.force_authenticate(self.user)
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
        self._authenticate_bounty_manager()

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
        """Test metrics included in bounty response from unified document"""
        # Arrange
        self._authenticate_bounty_manager()

        # Set a specific score on the unified document
        unified_document = self.comment.thread.content_object.unified_document
        unified_document.score = 42
        unified_document.save()

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

        # Test: Verify bounty metrics come from unified document
        comment_bounty_response = self.client.get(
            "/api/bounty/",
        )
        self.assertEqual(comment_bounty_response.status_code, 200)
        self.assertIn("metrics", comment_bounty_response.data["results"][0])

        # The metrics should contain votes from unified_document.score
        self.assertEqual(
            comment_bounty_response.data["results"][0]["metrics"]["votes"], 42
        )

    def test_assessment_end_date_included_in_get_bounties_action(self):
        """Test that assessment_end_date is included in get_bounties action response"""
        self._authenticate_bounty_manager()

        # Create a bounty
        self.client.post(
            "/api/bounty/",
            {
                "amount": 1000,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        # Get bounties using the get_bounties action endpoint
        res = self.client.get("/api/bounty/get_bounties/")

        self.assertEqual(res.status_code, 200)
        self.assertGreater(len(res.data), 0)
        # Verify assessment_end_date is included in response
        self.assertIn("assessment_end_date", res.data[0])

    def test_user_can_approve_full_amount_to_multiple_solutions(self):
        self._authenticate_bounty_manager()
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
        self._authenticate_bounty_manager()
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
        self._authenticate_bounty_manager()
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
        self._authenticate_bounty_manager()
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
        amount = 1000
        award_amount_1 = 200
        award_amount_2 = 300
        total_award = award_amount_1 + award_amount_2

        bounty_res = self.test_user_can_create_bounty(amount=amount)
        bounty_id = bounty_res.data["id"]
        bounty = Bounty.objects.get(id=bounty_id)

        recipient_1 = self.child_comment_1.created_by
        recipient_2 = self.child_comment_2.created_by

        initial_foundation_balance = self.foundation.get_balance()
        initial_recipient_1_balance = recipient_1.get_balance()
        initial_recipient_2_balance = recipient_2.get_balance()

        self._authenticate_bounty_manager()
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

        foundation_balance = self.foundation.get_balance()
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

        self.assertEqual(
            recipient_1_balance,
            initial_recipient_1_balance + decimal.Decimal(award_amount_1),
        )
        self.assertEqual(
            recipient_2_balance,
            initial_recipient_2_balance + decimal.Decimal(award_amount_2),
        )

        self.assertEqual(foundation_balance, initial_foundation_balance)

    def test_hubs_endpoint_returns_hubs_with_bounties(self):
        """Ensure /api/bounty/hubs/ returns hubs linked to open bounties."""
        # Arrange: create a hub linked paper and bounty
        paper = create_paper()
        paper.unified_document.hubs.add(self.hub)
        comment = create_rh_comment(created_by=self.user, paper=paper)
        self._authenticate_bounty_manager()
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
        self._authenticate_bounty_manager()
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
        self._authenticate_bounty_manager()
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
        self._authenticate_bounty_manager()
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

    def test_proposal_review_bounties_appear_first(self):
        """REVIEW bounties on PREREGISTRATION docs should sort before others."""
        # Arrange
        self._authenticate_bounty_manager()

        paper_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
                "bounty_type": Bounty.Type.REVIEW,
            },
        )
        self.assertEqual(paper_bounty_res.status_code, 201)

        prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        prereg_post = ResearchhubPost.objects.create(
            title="Proposal Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=prereg_doc,
        )
        prereg_comment = create_rh_comment(post=prereg_post, created_by=self.recipient)
        proposal_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": prereg_comment._meta.model_name,
                "item_object_id": prereg_comment.id,
                "bounty_type": Bounty.Type.REVIEW,
            },
        )
        self.assertEqual(proposal_bounty_res.status_code, 201)

        # Act
        res = self.client.get(
            "/api/bounty/",
            {"bounty_type": [Bounty.Type.REVIEW]},
        )

        # Assert
        self.assertEqual(res.status_code, 200)
        ids = [b["id"] for b in res.data["results"]]
        proposal_idx = ids.index(proposal_bounty_res.data["id"])
        paper_idx = ids.index(paper_bounty_res.data["id"])
        self.assertLess(
            proposal_idx,
            paper_idx,
            "Proposal review bounties should appear before other review bounties",
        )

    def test_proposal_review_bounties_appear_first_in_get_bounties(self):
        """get_bounties action should also prioritize proposal reviews."""
        # Arrange
        self._authenticate_bounty_manager()

        paper_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
                "bounty_type": Bounty.Type.REVIEW,
            },
        )
        self.assertEqual(paper_bounty_res.status_code, 201)

        prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        prereg_post = ResearchhubPost.objects.create(
            title="Proposal Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=prereg_doc,
        )
        prereg_comment = create_rh_comment(post=prereg_post, created_by=self.recipient)
        proposal_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": prereg_comment._meta.model_name,
                "item_object_id": prereg_comment.id,
                "bounty_type": Bounty.Type.REVIEW,
            },
        )
        self.assertEqual(proposal_bounty_res.status_code, 201)

        # Act
        res = self.client.get("/api/bounty/get_bounties/")

        # Assert
        self.assertEqual(res.status_code, 200)
        ids = [b["id"] for b in res.data]
        proposal_idx = ids.index(proposal_bounty_res.data["id"])
        paper_idx = ids.index(paper_bounty_res.data["id"])
        self.assertLess(
            proposal_idx,
            paper_idx,
            "Proposal review bounties should appear first in get_bounties",
        )

    def _create_paper_and_proposal_bounties(
        self, paper_amount=100, proposal_amount=100
    ):
        """Create a regular review bounty and a preregistration review bounty."""
        paper_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": paper_amount,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
                "bounty_type": Bounty.Type.REVIEW,
            },
        )
        self.assertEqual(paper_bounty_res.status_code, 201)

        prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        prereg_post = ResearchhubPost.objects.create(
            title="Proposal Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=prereg_doc,
        )
        prereg_comment = create_rh_comment(post=prereg_post, created_by=self.recipient)
        proposal_bounty_res = self.client.post(
            "/api/bounty/",
            {
                "amount": proposal_amount,
                "item_content_type": prereg_comment._meta.model_name,
                "item_object_id": prereg_comment.id,
                "bounty_type": Bounty.Type.REVIEW,
            },
        )
        self.assertEqual(proposal_bounty_res.status_code, 201)

        return paper_bounty_res.data["id"], proposal_bounty_res.data["id"]

    def test_personalized_sort_falls_back_to_default_when_logged_out(self):
        """Logged-out user requesting personalized sort gets default sort."""
        # Arrange
        self._authenticate_bounty_manager()
        paper_id, proposal_id = self._create_paper_and_proposal_bounties()
        self.client.logout()

        # Act
        res = self.client.get("/api/bounty/", {"sort": "personalized"})

        # Assert
        ids = [b["id"] for b in res.data["results"]]
        self.assertLess(ids.index(proposal_id), ids.index(paper_id))

    def test_preregistration_first_with_personalized_sort(self):
        """Personalized sort should prioritize proposal reviews."""
        # Arrange
        self._authenticate_bounty_manager()
        paper_id, proposal_id = self._create_paper_and_proposal_bounties()

        # Act
        res = self.client.get("/api/bounty/", {"sort": "personalized"})

        # Assert
        ids = [b["id"] for b in res.data["results"]]
        self.assertLess(ids.index(proposal_id), ids.index(paper_id))

    def test_preregistration_first_with_default_sort(self):
        """Default sort (-created_date) should prioritize proposal reviews."""
        # Arrange
        self._authenticate_bounty_manager()
        paper_id, proposal_id = self._create_paper_and_proposal_bounties()

        # Act
        res = self.client.get("/api/bounty/")

        # Assert
        ids = [b["id"] for b in res.data["results"]]
        self.assertLess(ids.index(proposal_id), ids.index(paper_id))

    def test_no_preregistration_priority_with_amount_sort(self):
        """Sorting by amount should not prioritize proposal reviews."""
        # Arrange
        self._authenticate_bounty_manager()
        paper_id, proposal_id = self._create_paper_and_proposal_bounties(
            paper_amount=500, proposal_amount=100
        )

        # Act
        res = self.client.get("/api/bounty/", {"sort": "-total_amount"})

        # Assert
        ids = [b["id"] for b in res.data["results"]]
        self.assertLess(ids.index(paper_id), ids.index(proposal_id))


class BountyAssessmentPhaseTests(APITestCase):
    """Tests for the bounty assessment phase functionality."""

    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.user = create_random_default_user("assessment_user")
        self.user_2 = create_random_default_user("assessment_user_2")
        self.recipient = create_random_default_user("assessment_recipient")
        self.foundation = create_user(email=FOUNDATION_EMAIL)

        self.comment = create_rh_comment(created_by=self.recipient)
        self.child_comment = create_rh_comment(
            created_by=self.user_2, parent=self.comment
        )
        self.hub = create_hub()
        self.bountyFee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        distribution = Dist("REWARD", 1000000000, give_rep=False)
        distributor = Distributor(
            distribution, self.user, self.user, time.time(), self.user
        )
        distributor.distribute()

        distributor = Distributor(
            distribution, self.user_2, self.user_2, time.time(), self.user_2
        )
        distributor.distribute()

        distributor = Distributor(
            distribution,
            self.foundation,
            self.foundation,
            time.time(),
            self.foundation,
        )
        distributor.distribute()

    def _authenticate_bounty_manager(self, user=None):
        self.client.force_authenticate(user or self.foundation)

    def _create_bounty(self, amount=100, expiration_date=None):
        """Helper to create a bounty."""
        data = {
            "amount": amount,
            "item_content_type": self.comment._meta.model_name,
            "item_object_id": self.comment.id,
        }
        if expiration_date:
            data["expiration_date"] = expiration_date.isoformat()

        response = self.client.post("/api/bounty/", data)
        return response

    @patch("reputation.tasks.send_email")
    def test_bounty_transitions_to_assessment_when_expiration_passes(
        self, mock_send_email
    ):
        """Test OPEN bounty transitions to ASSESSMENT when expiration_date passes."""
        self._authenticate_bounty_manager()

        # Create bounty with past expiration
        past_expiration = datetime.now(UTC) - timedelta(hours=1)
        bounty_res = self._create_bounty(expiration_date=past_expiration)
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        bounty = Bounty.objects.get(id=bounty_id)
        self.assertEqual(bounty.status, Bounty.OPEN)
        self.assertIsNone(bounty.assessment_end_date)

        # Run the scheduled task
        check_open_bounties()

        bounty.refresh_from_db()
        self.assertEqual(bounty.status, Bounty.ASSESSMENT)
        self.assertIsNotNone(bounty.assessment_end_date)

        # Verify assessment_end_date is approximately ASSESSMENT_PERIOD_DAYS from now
        expected_end = datetime.now(UTC) + timedelta(days=ASSESSMENT_PERIOD_DAYS)
        time_diff = abs((bounty.assessment_end_date - expected_end).total_seconds())
        self.assertLess(time_diff, 60)  # Within 60 seconds

    def test_bounty_expires_when_assessment_period_ends(self):
        """Test that ASSESSMENT bounty expires when assessment_end_date passes."""
        self._authenticate_bounty_manager()

        # Create bounty and manually set to ASSESSMENT with past assessment_end_date
        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        bounty = Bounty.objects.get(id=bounty_id)
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) - timedelta(hours=1)
        bounty.save()

        initial_foundation_balance = self.foundation.get_balance()

        # Run the scheduled task
        check_open_bounties()

        bounty.refresh_from_db()
        self.assertEqual(bounty.status, Bounty.EXPIRED)

        # Verify refund was issued
        final_foundation_balance = self.foundation.get_balance()
        self.assertGreater(final_foundation_balance, initial_foundation_balance)

    def test_creator_can_award_during_assessment_phase(self):
        """Test that bounty creator can award solutions during ASSESSMENT phase."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Manually set bounty to ASSESSMENT phase
        bounty = Bounty.objects.get(id=bounty_id)
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) + timedelta(days=5)
        bounty.save()

        # Award the bounty
        approve_res = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": bounty_res.data["amount"],
                    "object_id": self.child_comment.id,
                    "content_type": self.child_comment._meta.model_name,
                }
            ],
        )

        self.assertEqual(approve_res.status_code, 200)

    def test_random_user_cannot_award_during_assessment_phase(self):
        """Test that non-creator cannot award solutions during ASSESSMENT phase."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Manually set bounty to ASSESSMENT phase
        bounty = Bounty.objects.get(id=bounty_id)
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) + timedelta(days=5)
        bounty.save()

        # Try to award as different user
        self.client.force_authenticate(self.user_2)
        approve_res = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": bounty_res.data["amount"],
                    "object_id": self.child_comment.id,
                    "content_type": self.child_comment._meta.model_name,
                }
            ],
        )

        self.assertEqual(approve_res.status_code, 403)

    def test_cannot_award_when_assessment_period_expired(self):
        """Test that awarding fails when assessment_end_date has passed."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Manually set bounty to ASSESSMENT phase with expired assessment_end_date
        bounty = Bounty.objects.get(id=bounty_id)
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) - timedelta(hours=1)
        bounty.save()

        # Try to award
        approve_res = self.client.post(
            f"/api/bounty/{bounty_id}/approve_bounty/",
            [
                {
                    "amount": bounty_res.data["amount"],
                    "object_id": self.child_comment.id,
                    "content_type": self.child_comment._meta.model_name,
                }
            ],
        )

        self.assertEqual(approve_res.status_code, 404)

    def test_creator_can_cancel_during_assessment_phase(self):
        """Test that bounty creator can cancel during ASSESSMENT phase."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Manually set bounty to ASSESSMENT phase
        bounty = Bounty.objects.get(id=bounty_id)
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) + timedelta(days=5)
        bounty.save()

        # Cancel the bounty
        cancel_res = self.client.post(f"/api/bounty/{bounty_id}/cancel_bounty/")

        self.assertEqual(cancel_res.status_code, 200)

        bounty.refresh_from_db()
        self.assertEqual(bounty.status, Bounty.CANCELLED)

    def test_random_user_cannot_cancel_during_assessment_phase(self):
        """Test that non-creator cannot cancel during ASSESSMENT phase."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Manually set bounty to ASSESSMENT phase
        bounty = Bounty.objects.get(id=bounty_id)
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) + timedelta(days=5)
        bounty.save()

        # Try to cancel as different user
        self.client.force_authenticate(self.user_2)
        cancel_res = self.client.post(f"/api/bounty/{bounty_id}/cancel_bounty/")

        self.assertEqual(cancel_res.status_code, 403)

    def test_contributing_during_assessment_not_allowed(self):
        """Backing an existing bounty is not allowed during ASSESSMENT."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty(amount=100)
        self.assertEqual(bounty_res.status_code, 201)

        bounty = Bounty.objects.get(id=bounty_res.data["id"])
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) + timedelta(days=5)
        bounty.save()

        contribute_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 200,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )

        self.assertEqual(contribute_res.status_code, 400)
        self.assertIn(
            "Contributions to existing bounties", contribute_res.data["detail"]
        )

    def test_open_bounty_with_future_expiration_stays_open(self):
        """Test that OPEN bounty with future expiration_date stays OPEN."""
        self._authenticate_bounty_manager()

        future_expiration = datetime.now(UTC) + timedelta(days=7)
        bounty_res = self._create_bounty(expiration_date=future_expiration)
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        bounty = Bounty.objects.get(id=bounty_id)
        self.assertEqual(bounty.status, Bounty.OPEN)

        # Run the scheduled task
        check_open_bounties()

        bounty.refresh_from_db()
        self.assertEqual(bounty.status, Bounty.OPEN)
        self.assertIsNone(bounty.assessment_end_date)

    def test_assessment_bounty_with_future_end_date_stays_assessment(self):
        """Test ASSESSMENT bounty with future assessment_end_date stays ASSESSMENT."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Set bounty to ASSESSMENT phase with future end date
        bounty = Bounty.objects.get(id=bounty_id)
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) + timedelta(days=5)
        bounty.save()

        # Run the scheduled task
        check_open_bounties()

        bounty.refresh_from_db()
        self.assertEqual(bounty.status, Bounty.ASSESSMENT)


class BountyNotificationTests(APITestCase):
    """Tests for bounty notification functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.bank_user = create_user(email="bank@researchhub.com")
        self.user = create_random_default_user("notification_user")
        self.user_2 = create_random_default_user("notification_user_2")
        self.user_3 = create_random_default_user("notification_user_3")
        self.recipient = create_random_default_user("notification_recipient")
        self.foundation = create_user(email=FOUNDATION_EMAIL)

        self.comment = create_rh_comment(created_by=self.recipient)
        self.child_comment_1 = create_rh_comment(
            created_by=self.user_2, parent=self.comment
        )
        self.child_comment_2 = create_rh_comment(
            created_by=self.user_3, parent=self.comment
        )
        self.hub = create_hub()
        self.bountyFee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        distribution = Dist("REWARD", 1000000000, give_rep=False)
        distributor = Distributor(
            distribution, self.user, self.user, time.time(), self.user
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
            distribution,
            self.foundation,
            self.foundation,
            time.time(),
            self.foundation,
        )
        distributor.distribute()

    def _authenticate_bounty_manager(self, user=None):
        self.client.force_authenticate(user or self.foundation)

    def _create_bounty(self, amount=100, expiration_date=None):
        """Helper to create a bounty."""
        data = {
            "amount": amount,
            "item_content_type": self.comment._meta.model_name,
            "item_object_id": self.comment.id,
        }
        if expiration_date:
            data["expiration_date"] = expiration_date.isoformat()

        response = self.client.post("/api/bounty/", data)
        return response

    @patch("reputation.tasks.send_email")
    def test_bounty_expiring_soon_notification_sent(self, mock_send_email):
        """Test that BOUNTY_EXPIRING_SOON notification is sent 24h before expiration."""
        self._authenticate_bounty_manager()

        # Create bounty expiring in 23 hours (within 24h window)
        expiration_date = datetime.now(UTC) + timedelta(hours=23)
        bounty_res = self._create_bounty(expiration_date=expiration_date)
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Clear any existing notifications
        Notification.objects.filter(
            object_id=bounty_id, content_type=ContentType.objects.get_for_model(Bounty)
        ).delete()

        # Run the scheduled task
        check_open_bounties()

        # Verify notification was created
        notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_EXPIRING_SOON,
        ).first()

        self.assertIsNotNone(notification)
        self.assertEqual(notification.recipient, self.foundation)
        self.assertEqual(
            notification.notification_type, Notification.BOUNTY_EXPIRING_SOON
        )

    @patch("reputation.tasks.send_email")
    def test_bounty_expiring_soon_notification_not_sent_twice(self, mock_send_email):
        """Test that BOUNTY_EXPIRING_SOON notification is not sent twice."""
        self._authenticate_bounty_manager()

        expiration_date = datetime.now(UTC) + timedelta(hours=23)
        bounty_res = self._create_bounty(expiration_date=expiration_date)
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Run task once
        check_open_bounties()

        # Count notifications
        notification_count_before = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_EXPIRING_SOON,
        ).count()

        # Run task again
        check_open_bounties()

        # Verify notification count didn't increase
        notification_count_after = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_EXPIRING_SOON,
        ).count()

        self.assertEqual(notification_count_before, notification_count_after)
        self.assertEqual(notification_count_before, 1)

    @patch("reputation.tasks.send_email")
    def test_bounty_entered_assessment_notification_sent_to_creator(
        self, mock_send_email
    ):
        """Test that BOUNTY_ENTERED_ASSESSMENT notification is sent to creator."""
        self._authenticate_bounty_manager()

        # Create bounty with past expiration
        past_expiration = datetime.now(UTC) - timedelta(hours=1)
        bounty_res = self._create_bounty(expiration_date=past_expiration)
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Clear any existing notifications
        Notification.objects.filter(
            object_id=bounty_id, content_type=ContentType.objects.get_for_model(Bounty)
        ).delete()

        # Run the scheduled task
        check_open_bounties()

        # Verify notification was created for creator
        notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_ENTERED_ASSESSMENT,
            recipient=self.foundation,
        ).first()

        self.assertIsNotNone(notification)
        self.assertEqual(notification.recipient, self.foundation)
        self.assertEqual(
            notification.notification_type, Notification.BOUNTY_ENTERED_ASSESSMENT
        )

    @patch("reputation.tasks.send_email")
    def test_bounty_solution_in_assessment_notification_sent_to_reviewers(
        self, mock_send_email
    ):
        """Test that BOUNTY_SOLUTION_IN_ASSESSMENT notification is sent to reviewers."""
        self._authenticate_bounty_manager()

        # Create bounty
        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        bounty = Bounty.objects.get(id=bounty_id)

        # Get the paper/document that the bounty is attached to
        paper = self.comment.thread.content_object

        # Create peer review comments on the same document (simulating reviewers)
        thread_2 = RhCommentThreadModel.objects.create(
            content_object=paper,
            created_by=self.user_2,
            updated_by=self.user_2,
        )
        RhCommentModel.objects.create(
            comment_content_json={"text": "Peer review by user 2"},
            thread=thread_2,
            created_by=self.user_2,
            updated_by=self.user_2,
            comment_type=PEER_REVIEW,
        )

        thread_3 = RhCommentThreadModel.objects.create(
            content_object=paper,
            created_by=self.user_3,
            updated_by=self.user_3,
        )
        RhCommentModel.objects.create(
            comment_content_json={"text": "Peer review by user 3"},
            thread=thread_3,
            created_by=self.user_3,
            updated_by=self.user_3,
            comment_type=PEER_REVIEW,
        )

        # Set bounty to expired so it transitions to ASSESSMENT
        bounty.expiration_date = datetime.now(UTC) - timedelta(hours=1)
        bounty.save()

        # Clear any existing notifications
        Notification.objects.filter(
            object_id=bounty_id, content_type=ContentType.objects.get_for_model(Bounty)
        ).delete()

        # Run the scheduled task
        check_open_bounties()

        # Verify notifications were created for reviewers
        reviewer_2_notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
            recipient=self.user_2,
        ).first()

        reviewer_3_notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
            recipient=self.user_3,
        ).first()

        self.assertIsNotNone(reviewer_2_notification)
        self.assertIsNotNone(reviewer_3_notification)
        self.assertEqual(reviewer_2_notification.recipient, self.user_2)
        self.assertEqual(reviewer_3_notification.recipient, self.user_3)

    @patch("reputation.tasks.send_email")
    def test_bounty_solution_notification_not_sent_to_creator(self, mock_send_email):
        """Test reviewers get notification, creator doesn't get it."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        bounty = Bounty.objects.get(id=bounty_id)

        # Get the paper/document that the bounty is attached to
        paper = self.comment.thread.content_object

        # Create peer review comment by another user
        thread_2 = RhCommentThreadModel.objects.create(
            content_object=paper,
            created_by=self.user_2,
            updated_by=self.user_2,
        )
        RhCommentModel.objects.create(
            comment_content_json={"text": "Peer review by user 2"},
            thread=thread_2,
            created_by=self.user_2,
            updated_by=self.user_2,
            comment_type=PEER_REVIEW,
        )

        # Set bounty to expired
        bounty.expiration_date = datetime.now(UTC) - timedelta(hours=1)
        bounty.save()

        # Clear notifications
        Notification.objects.filter(
            object_id=bounty_id, content_type=ContentType.objects.get_for_model(Bounty)
        ).delete()

        # Run task
        check_open_bounties()

        # Creator should NOT get BOUNTY_SOLUTION_IN_ASSESSMENT notification
        creator_reviewer_notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
            recipient=self.user,
        ).exists()

        self.assertFalse(creator_reviewer_notification)

    @patch("reputation.tasks.send_email")
    def test_bounty_assessment_expiring_soon_notification_sent(self, mock_send_email):
        """Test BOUNTY_ASSESSMENT_EXPIRING_SOON sent 24h before assessment ends."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Set bounty to ASSESSMENT with assessment_end_date in 23 hours
        bounty = Bounty.objects.get(id=bounty_id)
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) + timedelta(hours=23)
        bounty.save()

        # Clear notifications
        Notification.objects.filter(
            object_id=bounty_id, content_type=ContentType.objects.get_for_model(Bounty)
        ).delete()

        # Run the scheduled task
        check_open_bounties()

        # Verify notification was created
        notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_ASSESSMENT_EXPIRING_SOON,
        ).first()

        self.assertIsNotNone(notification)
        self.assertEqual(notification.recipient, self.foundation)
        self.assertEqual(
            notification.notification_type, Notification.BOUNTY_ASSESSMENT_EXPIRING_SOON
        )

    @patch("reputation.tasks.send_email")
    def test_bounty_assessment_expiring_notification_not_sent_twice(
        self, mock_send_email
    ):
        """Test that BOUNTY_ASSESSMENT_EXPIRING_SOON notification is not sent twice."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Set bounty to ASSESSMENT
        bounty = Bounty.objects.get(id=bounty_id)
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(UTC) + timedelta(hours=23)
        bounty.save()

        # Run task once
        check_open_bounties()

        # Count notifications
        notification_count_before = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_ASSESSMENT_EXPIRING_SOON,
        ).count()

        # Run task again
        check_open_bounties()

        # Verify notification count didn't increase
        notification_count_after = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_ASSESSMENT_EXPIRING_SOON,
        ).count()

        self.assertEqual(notification_count_before, notification_count_after)
        self.assertEqual(notification_count_before, 1)

    def test_no_notification_when_bounty_not_in_time_window(self):
        """Test notifications are not sent when bounties are outside time windows."""
        self._authenticate_bounty_manager()

        # Create bounty expiring in 2 days (outside 24h window)
        expiration_date = datetime.now(UTC) + timedelta(days=2)
        bounty_res = self._create_bounty(expiration_date=expiration_date)
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        # Clear notifications
        Notification.objects.filter(
            object_id=bounty_id, content_type=ContentType.objects.get_for_model(Bounty)
        ).delete()

        # Run task
        check_open_bounties()

        # Verify no notification was created
        notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_EXPIRING_SOON,
        ).exists()

        self.assertFalse(notification)

    @patch("reputation.tasks.send_email")
    def test_all_peer_reviewers_get_notification(self, mock_send_email):
        """Test that all peer reviewers get notified when bounty enters assessment."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        bounty = Bounty.objects.get(id=bounty_id)

        # Get the paper/document that the bounty is attached to
        paper = self.comment.thread.content_object

        # Create peer review comments by multiple users
        thread_2 = RhCommentThreadModel.objects.create(
            content_object=paper,
            created_by=self.user_2,
            updated_by=self.user_2,
        )
        RhCommentModel.objects.create(
            comment_content_json={"text": "Peer review by user 2"},
            thread=thread_2,
            created_by=self.user_2,
            updated_by=self.user_2,
            comment_type=PEER_REVIEW,
        )

        thread_3 = RhCommentThreadModel.objects.create(
            content_object=paper,
            created_by=self.user_3,
            updated_by=self.user_3,
        )
        RhCommentModel.objects.create(
            comment_content_json={"text": "Peer review by user 3"},
            thread=thread_3,
            created_by=self.user_3,
            updated_by=self.user_3,
            comment_type=PEER_REVIEW,
        )

        # Set bounty to expired
        bounty.expiration_date = datetime.now(UTC) - timedelta(hours=1)
        bounty.save()

        # Clear notifications
        Notification.objects.filter(
            object_id=bounty_id, content_type=ContentType.objects.get_for_model(Bounty)
        ).delete()

        # Run task
        check_open_bounties()

        # Verify both peer reviewers got notifications
        user_2_notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
            recipient=self.user_2,
        ).exists()

        user_3_notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
            recipient=self.user_3,
        ).exists()

        self.assertTrue(user_2_notification)
        self.assertTrue(user_3_notification)

    @patch("reputation.tasks.send_email")
    def test_solution_submitters_also_get_notification(self, mock_send_email):
        """Test that solution submitters with SUBMITTED status also get notified."""
        self._authenticate_bounty_manager()

        bounty_res = self._create_bounty()
        self.assertEqual(bounty_res.status_code, 201)
        bounty_id = bounty_res.data["id"]

        bounty = Bounty.objects.get(id=bounty_id)

        # Get the paper/document that the bounty is attached to
        paper = self.comment.thread.content_object

        # Create a peer review comment by user_2
        thread_2 = RhCommentThreadModel.objects.create(
            content_object=paper,
            created_by=self.user_2,
            updated_by=self.user_2,
        )
        RhCommentModel.objects.create(
            comment_content_json={"text": "Peer review by user 2"},
            thread=thread_2,
            created_by=self.user_2,
            updated_by=self.user_2,
            comment_type=PEER_REVIEW,
        )

        # Create a BountySolution by user_3 (not a peer reviewer)
        BountySolution.objects.create(
            bounty=bounty,
            created_by=self.user_3,
            content_type=ContentType.objects.get_for_model(self.child_comment_2),
            object_id=self.child_comment_2.id,
            status=BountySolution.Status.SUBMITTED,
        )

        # Set bounty to expired
        bounty.expiration_date = datetime.now(UTC) - timedelta(hours=1)
        bounty.save()

        # Clear notifications
        Notification.objects.filter(
            object_id=bounty_id, content_type=ContentType.objects.get_for_model(Bounty)
        ).delete()

        # Run task
        check_open_bounties()

        # Verify both peer reviewer (user_2) and solution submitter (user_3)
        # got notifications
        user_2_notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
            recipient=self.user_2,
        ).exists()

        user_3_notification = Notification.objects.filter(
            object_id=bounty_id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
            recipient=self.user_3,
        ).exists()

        self.assertTrue(user_2_notification)
        self.assertTrue(user_3_notification)
