import decimal
import threading
import time
from datetime import datetime, timedelta

import pytz
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from paper.tests.helpers import create_paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Bounty, BountyFee, Distribution, Escrow
from researchhub_comment.tests.helpers import create_rh_comment
from user.tests.helpers import create_random_default_user, create_user


class EscrowPayoutDistributionTypeTests(APITestCase):
    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.user = create_random_default_user("escrow_payout_user")
        self.recipient = create_random_default_user("escrow_payout_recipient")
        self.comment = create_rh_comment(created_by=self.recipient)
        self.bounty_fee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        distribution = Dist("REWARD", 1000000000, give_rep=False)
        Distributor(
            distribution, self.user, self.user, time.time(), self.user
        ).distribute()
        Distributor(
            distribution, self.recipient, self.recipient, time.time(), self.recipient
        ).distribute()

    def _create_bounty(self, amount=100):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/bounty/",
            {
                "amount": amount,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(response.status_code, 201)
        return response

    def test_bounty_escrow_payout_uses_bounty_payout_distribution_type(self):
        bounty_res = self._create_bounty()
        bounty = Bounty.objects.get(id=bounty_res.data["id"])
        escrow = bounty.escrow

        paid = escrow.payout(recipient=self.recipient, payout_amount=decimal.Decimal(100))
        self.assertTrue(paid)

        distribution = Distribution.objects.filter(
            proof_item_object_id=escrow.id,
            recipient=self.recipient,
        ).latest("id")
        self.assertEqual(distribution.distribution_type, "BOUNTY_PAYOUT")

    def test_author_rsc_escrow_payout_uses_stored_paper_pot_distribution_type(self):
        paper = create_paper()
        escrow = Escrow.objects.create(
            hold_type=Escrow.AUTHOR_RSC,
            amount_holding=decimal.Decimal("25"),
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(paper),
            object_id=paper.id,
        )

        paid = escrow.payout(recipient=self.recipient, payout_amount=decimal.Decimal("25"))
        self.assertTrue(paid)

        distribution = Distribution.objects.filter(
            proof_item_object_id=escrow.id,
            recipient=self.recipient,
        ).latest("id")
        self.assertEqual(distribution.distribution_type, "STORED_PAPER_POT")


class EscrowPayoutApproveBountyTests(APITestCase):
    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.user = create_random_default_user("approve_bounty_user")
        self.recipient = create_random_default_user("approve_bounty_recipient")
        self.comment = create_rh_comment(created_by=self.recipient)
        self.child_comment = create_rh_comment(
            created_by=self.recipient, parent=self.comment
        )
        self.bounty_fee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        distribution = Dist("REWARD", 1000000000, give_rep=False)
        Distributor(
            distribution, self.user, self.user, time.time(), self.user
        ).distribute()

    def _create_bounty_in_assessment(self, amount=100):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/bounty/",
            {
                "amount": amount,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(response.status_code, 201)
        bounty = Bounty.objects.get(id=response.data["id"])
        bounty.status = Bounty.ASSESSMENT
        bounty.assessment_end_date = datetime.now(pytz.UTC) + timedelta(days=5)
        bounty.save()
        return bounty

    def test_creator_cannot_award_own_solution(self):
        own_comment = create_rh_comment(created_by=self.user, parent=self.comment)
        bounty = self._create_bounty_in_assessment()

        response = self.client.post(
            f"/api/bounty/{bounty.id}/approve_bounty/",
            [
                {
                    "amount": "100",
                    "object_id": own_comment.id,
                    "content_type": own_comment._meta.model_name,
                }
            ],
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["detail"], "Cannot award your own solution")

    def test_cannot_re_award_already_awarded_solution(self):
        bounty = self._create_bounty_in_assessment(amount=200)
        payload = [
            {
                "amount": "100",
                "object_id": self.child_comment.id,
                "content_type": self.child_comment._meta.model_name,
            }
        ]

        first_response = self.client.post(
            f"/api/bounty/{bounty.id}/approve_bounty/", payload
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            f"/api/bounty/{bounty.id}/approve_bounty/", payload
        )
        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(
            second_response.data["detail"], "Solution has already been awarded"
        )


class EscrowPayoutConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.user = create_random_default_user("concurrency_user")
        self.recipient = create_random_default_user("concurrency_recipient")
        self.comment = create_rh_comment(created_by=self.recipient)
        self.child_comment = create_rh_comment(
            created_by=self.recipient, parent=self.comment
        )
        BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        distribution = Dist("REWARD", 1000000000, give_rep=False)
        Distributor(
            distribution, self.user, self.user, time.time(), self.user
        ).distribute()

        client = APIClient()
        client.force_authenticate(self.user)
        bounty_res = client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(bounty_res.status_code, 201)
        self.bounty = Bounty.objects.get(id=bounty_res.data["id"])
        self.bounty.status = Bounty.ASSESSMENT
        self.bounty.assessment_end_date = datetime.now(pytz.UTC) + timedelta(days=5)
        self.bounty.save()
        self.escrow_id = self.bounty.escrow_id

    def test_concurrent_approve_bounty_only_pays_once(self):
        barrier = threading.Barrier(5)
        results = []
        errors = []

        def approve_once():
            try:
                client = APIClient()
                client.force_authenticate(self.user)
                barrier.wait()
                response = client.post(
                    f"/api/bounty/{self.bounty.id}/approve_bounty/",
                    [
                        {
                            "amount": "100",
                            "object_id": self.child_comment.id,
                            "content_type": self.child_comment._meta.model_name,
                        }
                    ],
                )
                results.append(response.status_code)
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=approve_once) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(sum(1 for status_code in results if status_code == 200), 1)

        self.bounty.escrow.refresh_from_db()
        self.assertEqual(self.bounty.escrow.amount_holding, decimal.Decimal("0"))

        payout_count = Distribution.objects.filter(
            proof_item_object_id=self.escrow_id,
            distribution_type="BOUNTY_PAYOUT",
            recipient=self.recipient,
        ).count()
        self.assertEqual(payout_count, 1)
