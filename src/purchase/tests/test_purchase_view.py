from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APITestCase

from notification.models import Notification
from paper.tests.helpers import create_paper
from purchase.models import Balance, Purchase, RscExchangeRate
from purchase.permissions import CanTipOrReadOnly
from reputation.models import BountyFee, Escrow, SupportFee
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    GENERIC_COMMENT,
    PEER_REVIEW,
)
from researchhub_comment.tests.helpers import create_rh_comment
from researchhub_document.helpers import create_post
from review.models import Review
from user.related_models.user_model import FOUNDATION_EMAIL
from user.tests.helpers import (
    create_random_authenticated_user,
    create_user,
)

STARTING_BALANCE = Decimal(10000)
PER_TIP_LIMIT_RSC = 600
DAILY_LIMIT_RSC = 10000


class PurchaseViewTests(APITestCase):
    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.foundation = create_user(email=FOUNDATION_EMAIL)
        self.bountyFee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)
        self.supportFee = SupportFee.objects.create(rh_pct=0.03, dao_pct=0.00)
        self.distribution_ct = ContentType.objects.get(model="distribution")
        self._fund(self.foundation)

        RscExchangeRate.objects.create(
            rate=0.5,
            real_rate=0.5,
            target_currency="USD",
        )

    def _fund(self, user, amount=STARTING_BALANCE):
        Balance.objects.create(
            amount=str(amount), user=user, content_type=self.distribution_ct
        )

    def _create_review_comment(self, poster, post=None, comment_type=COMMUNITY_REVIEW):
        comment = create_rh_comment(created_by=poster, post=post)
        comment.comment_type = comment_type
        comment.save()
        return comment

    def _record_past_tip(self, comment, amount, age=timedelta(0)):
        purchase = Purchase.objects.create(
            user=self.foundation,
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.id,
            purchase_type=Purchase.BOOST,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount=str(amount),
        )
        Purchase.objects.filter(id=purchase.id).update(
            created_date=timezone.now() - age
        )
        return purchase

    def _post_support_response(
        self, user, object_id, content_type, amount=10, purchase_type="BOOST"
    ):
        url = "/api/purchase/"
        self.client.force_authenticate(user)
        return self.client.post(
            url,
            {
                "amount": amount,
                "content_type": content_type,
                "object_id": object_id,
                "purchase_method": "OFF_CHAIN",
                "purchase_type": purchase_type,
            },
        )

    def _assert_no_tip_was_made(self, tipper, recipient, tipper_balance=None):
        """Nothing was recorded and neither side's balance moved."""
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(
            tipper.get_balance(),
            STARTING_BALANCE if tipper_balance is None else tipper_balance,
        )
        self.assertEqual(Balance.objects.filter(user=tipper).count(), 1)
        self.assertEqual(recipient.get_balance(), 0)
        self.assertFalse(Balance.objects.filter(user=recipient).exists())
        self.assertFalse(Notification.objects.filter(recipient=recipient).exists())

    def test_list_purchases(self):
        # Arrange
        poster = create_random_authenticated_user("rep_user")
        comment = self._create_review_comment(poster)
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", 100
        )
        self.assertContains(response, "id", status_code=201)

        # Act
        self.client.force_authenticate(self.foundation)
        response = self.client.get("/api/purchase/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    def test_list_purchases_cannot_list_other_users_purchases(self):
        # Arrange
        poster = create_random_authenticated_user("rep_user")
        comment = self._create_review_comment(poster)
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", 100
        )
        self.assertContains(response, "id", status_code=201)

        # Act
        self.client.force_authenticate(poster)
        response = self.client.get("/api/purchase/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 0)

    def test_ordinary_user_can_still_list_past_tips(self):
        """Tips made before the restriction stay readable by their owner."""
        # Arrange
        tipper = create_random_authenticated_user("past_tipper")
        poster = create_random_authenticated_user("poster")
        comment = create_rh_comment(created_by=poster)
        past_tip = Purchase.objects.create(
            user=tipper,
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.id,
            purchase_type=Purchase.BOOST,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount="100",
        )

        # Act
        self.client.force_authenticate(tipper)
        response = self.client.get("/api/purchase/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [result["id"] for result in response.data["results"]], [past_tip.id]
        )
        self.assertEqual(response.data["results"][0]["purchase_type"], Purchase.BOOST)

    def test_support_paper_is_rejected(self):
        # Arrange
        uploader = create_random_authenticated_user("rep_user")
        paper = create_paper(uploaded_by=uploader)

        # Act
        response = self._post_support_response(self.foundation, paper.id, "paper", 10)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Escrow.objects.filter(hold_type=Escrow.AUTHOR_RSC).count(), 0)

    def test_foundation_account_can_tip(self):
        # Arrange
        poster = create_random_authenticated_user("rep_user")
        post = create_post(created_by=poster)
        comment = self._create_review_comment(poster, post=post)
        tip_amount = 100
        fee_amount = 3

        # Act
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", tip_amount
        )

        # Assert
        self.assertContains(response, "id", status_code=201)
        purchase = Purchase.objects.get(id=response.data["id"])
        self.assertEqual(purchase.user, self.foundation)
        self.assertEqual(purchase.purchase_type, Purchase.BOOST)
        self.assertEqual(purchase.paid_status, Purchase.PAID)
        # fee and tip deducted from the Foundation account
        fee_balance_entry = Balance.objects.filter(
            user=self.foundation,
            content_type=ContentType.objects.get_for_model(SupportFee),
        )
        self.assertTrue(fee_balance_entry.exists())
        self.assertEqual(float(fee_balance_entry.first().amount), float(-fee_amount))
        amount_balance_entry = Balance.objects.filter(
            user=self.foundation,
            content_type=ContentType.objects.get(model="purchase"),
            object_id=purchase.id,
        )
        self.assertTrue(amount_balance_entry.exists())
        self.assertEqual(float(amount_balance_entry.first().amount), float(-tip_amount))
        self.assertEqual(
            self.foundation.get_balance(),
            STARTING_BALANCE - tip_amount - fee_amount,
        )
        # tip credited to the poster
        poster_balance_entry = Balance.objects.filter(
            user=poster, content_type=self.distribution_ct
        )
        self.assertTrue(poster_balance_entry.exists())
        self.assertEqual(
            float(poster_balance_entry.latest("created_date").amount),
            float(tip_amount),
        )
        self.assertEqual(poster.get_balance(), tip_amount)

    def test_ordinary_user_cannot_tip(self):
        # Arrange
        user = create_random_authenticated_user("tipper")
        poster = create_random_authenticated_user("poster")
        comment = create_rh_comment(created_by=poster)
        self._fund(user)

        # Act
        response = self._post_support_response(user, comment.id, "rhcommentmodel", 100)

        # Assert
        self.assertEqual(response.status_code, 403)
        self._assert_no_tip_was_made(user, poster)

    def test_moderator_and_staff_cannot_tip(self):
        # Arrange
        moderator = create_random_authenticated_user("moderator", moderator=True)
        staff = create_random_authenticated_user("staff")
        staff.is_staff = True
        staff.is_superuser = True
        staff.save()
        poster = create_random_authenticated_user("poster")
        comment = create_rh_comment(created_by=poster)

        for user in (moderator, staff):
            with self.subTest(user=user.email):
                self._fund(user)

                # Act
                response = self._post_support_response(
                    user, comment.id, "rhcommentmodel", 100
                )

                # Assert
                self.assertEqual(response.status_code, 403)
                self._assert_no_tip_was_made(user, poster)

    def test_ordinary_user_cannot_tip_under_another_purchase_type(self):
        """The restriction covers the endpoint, not just the BOOST label."""
        # Arrange
        user = create_random_authenticated_user("tipper")
        poster = create_random_authenticated_user("poster")
        comment = create_rh_comment(created_by=poster)
        self._fund(user)

        for purchase_type in (
            Purchase.DOI,
            Purchase.FUNDRAISE_CONTRIBUTION,
            Purchase.FUNDING_POOL_CONTRIBUTION,
        ):
            with self.subTest(purchase_type=purchase_type):
                # Act
                response = self._post_support_response(
                    user, comment.id, "rhcommentmodel", 100, purchase_type
                )

                # Assert
                self.assertEqual(response.status_code, 403)
                self._assert_no_tip_was_made(user, poster)

    def test_fallback_account_cannot_tip_without_a_foundation_account(self):
        """The bank account stands in as community account when none exists."""
        # Arrange
        self.foundation.delete(soft=False)
        poster = create_random_authenticated_user("poster")
        comment = create_rh_comment(created_by=poster)
        self._fund(self.bank_user)

        # Act
        response = self._post_support_response(
            self.bank_user, comment.id, "rhcommentmodel", 100
        )

        # Assert
        self.assertEqual(response.status_code, 403)
        self._assert_no_tip_was_made(self.bank_user, poster)

    def test_tip_is_refused_inside_the_transaction_without_the_permission(self):
        """The view refuses on its own if the permission class is bypassed."""
        # Arrange
        user = create_random_authenticated_user("tipper")
        poster = create_random_authenticated_user("poster")
        comment = create_rh_comment(created_by=poster)
        self._fund(user)

        # Act
        with patch.object(CanTipOrReadOnly, "has_permission", return_value=True):
            response = self._post_support_response(
                user, comment.id, "rhcommentmodel", 100
            )

        # Assert
        self.assertEqual(response.status_code, 403)
        self._assert_no_tip_was_made(user, poster)

    def test_unauthenticated_request_cannot_tip(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = create_rh_comment(created_by=poster)

        # Act
        response = self._post_support_response(None, comment.id, "rhcommentmodel", 100)

        # Assert
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertFalse(Balance.objects.filter(user=poster).exists())

    def test_tip_notifies_the_review_author(self) -> None:
        # Arrange
        poster = create_random_authenticated_user("poster")

        for comment_type in (COMMUNITY_REVIEW, PEER_REVIEW):
            with self.subTest(comment_type=comment_type):
                comment = self._create_review_comment(poster, comment_type=comment_type)

                # Act
                response = self._post_support_response(
                    self.foundation, comment.id, "rhcommentmodel", 100
                )

                # Assert
                self.assertEqual(response.status_code, 201)
                self.assertEqual(
                    Notification.objects.filter(recipient=poster)
                    .latest("id")
                    .notification_type,
                    Notification.RSC_SUPPORT_ON_DOC,
                )

    def test_tip_marks_the_review_assessed(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = self._create_review_comment(poster)
        review = Review.objects.create(
            created_by=poster,
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.id,
            unified_document=comment.unified_document,
            score=7,
        )

        # Act
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", 100
        )

        # Assert
        self.assertEqual(response.status_code, 201)
        review.refresh_from_db()
        self.assertTrue(review.is_assessed)

    def test_tip_on_a_comment_that_is_not_a_review_is_rejected(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = self._create_review_comment(poster, comment_type=GENERIC_COMMENT)

        # Act
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", 100
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self._assert_no_tip_was_made(self.foundation, poster)

    def test_tip_on_a_missing_comment_is_rejected(self):
        # Arrange
        poster = create_random_authenticated_user("poster")

        for object_id in (0, "not-a-number"):
            with self.subTest(object_id=object_id):
                # Act
                response = self._post_support_response(
                    self.foundation, object_id, "rhcommentmodel", 100
                )

                # Assert
                self.assertEqual(response.status_code, 400)
                self._assert_no_tip_was_made(self.foundation, poster)

    def test_tip_at_the_per_tip_limit_is_accepted(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = self._create_review_comment(poster)

        # Act
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", PER_TIP_LIMIT_RSC
        )

        # Assert
        self.assertEqual(response.status_code, 201)
        self.assertEqual(poster.get_balance(), PER_TIP_LIMIT_RSC)

    def test_tip_above_the_per_tip_limit_is_rejected(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = self._create_review_comment(poster)

        # Act
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", PER_TIP_LIMIT_RSC + 1
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self._assert_no_tip_was_made(self.foundation, poster)

    def test_tip_above_the_daily_limit_is_rejected(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = self._create_review_comment(poster)
        self._record_past_tip(comment, DAILY_LIMIT_RSC - 100)

        # Act
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", 101
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Purchase.objects.count(), 1)
        self.assertEqual(self.foundation.get_balance(), STARTING_BALANCE)
        self.assertEqual(poster.get_balance(), 0)

    def test_tip_reaching_the_daily_limit_is_accepted(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = self._create_review_comment(poster)
        self._record_past_tip(comment, DAILY_LIMIT_RSC - 100)

        # Act
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", 100
        )

        # Assert
        self.assertEqual(response.status_code, 201)

    def test_tips_older_than_the_window_do_not_count_toward_the_daily_limit(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = self._create_review_comment(poster)
        self._record_past_tip(comment, DAILY_LIMIT_RSC, age=timedelta(hours=25))

        # Act
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", 100
        )

        # Assert
        self.assertEqual(response.status_code, 201)

    def test_invalid_purchase_method_is_rejected(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = create_rh_comment(created_by=poster)

        # Act
        self.client.force_authenticate(self.foundation)
        response = self.client.post(
            "/api/purchase/",
            {
                "amount": 100,
                "content_type": "rhcommentmodel",
                "object_id": comment.id,
                "purchase_method": "ON_CHAIN",
                "purchase_type": "BOOST",
            },
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self._assert_no_tip_was_made(self.foundation, poster)

    def test_invalid_purchase_type_is_rejected(self):
        # Arrange
        poster = create_random_authenticated_user("poster")
        comment = create_rh_comment(created_by=poster)

        for purchase_type in (
            Purchase.DOI,
            Purchase.FUNDRAISE_CONTRIBUTION,
            Purchase.FUNDING_POOL_CONTRIBUTION,
        ):
            with self.subTest(purchase_type=purchase_type):
                # Act
                response = self._post_support_response(
                    self.foundation, comment.id, "rhcommentmodel", 100, purchase_type
                )

                # Assert
                self.assertEqual(response.status_code, 400)
                self._assert_no_tip_was_made(self.foundation, poster)

    def test_probable_spammer_cannot_support(self):
        # Arrange
        poster = create_random_authenticated_user("poster_user")
        comment = create_rh_comment(created_by=poster)
        self.foundation.probable_spammer = True
        self.foundation.save()

        # Act
        response = self._post_support_response(
            self.foundation, comment.id, "rhcommentmodel", 100
        )

        # Assert
        self.assertEqual(response.status_code, 403)
        self._assert_no_tip_was_made(self.foundation, poster)
