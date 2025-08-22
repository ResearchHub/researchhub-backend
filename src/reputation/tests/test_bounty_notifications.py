from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APITestCase

from notification.models import Notification
from reputation.models import Bounty
from reputation.tasks import check_open_bounties
from researchhub_comment.tests.helpers import create_rh_comment
from user.tests.helpers import create_random_default_user


class BountyNotificationTests(APITestCase):
    def setUp(self):
        from purchase.models import Balance
        from django.contrib.contenttypes.models import ContentType
        from user.models import User
        
        if not User.objects.filter(id=1).exists():
            User.objects.create_user(
                username="revenue",
                email="revenue@researchhub.com",
                id=1
            )
        
        self.user = create_random_default_user("bounty_creator")
        self.submitter = create_random_default_user("solution_submitter")
        
        Balance.objects.create(
            user=self.user,
            amount="1000",
            content_type=ContentType.objects.get_for_model(self.user)
        )
        
        self.comment = create_rh_comment(created_by=self.user)
        
    def test_review_period_notifications_sent(self):
        """Test that notifications are sent when bounty enters review period."""
        self.client.force_authenticate(self.user)
        create_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        self.assertEqual(create_res.status_code, 201)
        
        bounty = Bounty.objects.get(id=create_res.data["id"])
        from researchhub_comment.models import RhCommentModel
        
        submitter_comment = RhCommentModel.objects.create(
            comment_content_json={"text": "This is my solution"},
            thread=self.comment.thread,
            created_by=self.submitter,
            updated_by=self.submitter,
        )
        
        bounty.expiration_date = timezone.now() - timedelta(hours=1)
        bounty.save()
        
        check_open_bounties()
        creator_notification = Notification.objects.filter(
            recipient=self.user,
            notification_type=Notification.BOUNTY_REVIEW_PERIOD_STARTED
        ).first()
        self.assertIsNotNone(creator_notification)
        
        submitter_notification = Notification.objects.filter(
            recipient=self.submitter,
            notification_type=Notification.BOUNTY_REVIEW_PERIOD_STARTED
        ).first()
        self.assertIsNotNone(submitter_notification)
        
    def test_review_period_ending_notification(self):
        """Test that 24-hour warning is sent before review period ends."""
        self.client.force_authenticate(self.user)
        create_res = self.client.post(
            "/api/bounty/",
            {
                "amount": 100,
                "item_content_type": self.comment._meta.model_name,
                "item_object_id": self.comment.id,
            },
        )
        
        bounty = Bounty.objects.get(id=create_res.data["id"])
        bounty.status = Bounty.REVIEW_PERIOD
        bounty.expiration_date = timezone.now() - timedelta(days=9, hours=1)
        bounty.save()
        
        check_open_bounties()
        notification = Notification.objects.filter(
            recipient=self.user,
            notification_type=Notification.BOUNTY_REVIEW_PERIOD_ENDING_SOON
        ).first()
        self.assertIsNotNone(notification)