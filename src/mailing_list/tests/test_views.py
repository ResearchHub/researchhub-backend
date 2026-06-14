import json

from django.test import TransactionTestCase
from rest_framework.test import APIClient

from mailing_list.models import EmailRecipient
from user.tests.helpers import create_random_authenticated_user


class MailingListSNSEmailTests(TransactionTestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("mailing_user")

    def _post_notification(self, notification_type, payload):
        # Arrange
        message = {"notificationType": notification_type, **payload}
        data = json.dumps({"Type": "Notification", "Message": json.dumps(message)})

        # Act
        client = APIClient()
        client.force_authenticate(user=self.user, token=self.user.auth_token)
        return client.post("/email_notifications/", data, format="txt")

    def test_bounce_marks_do_not_email(self):
        # Act
        response = self._post_notification(
            "Bounce",
            {"bounce": {"bouncedRecipients": [{"emailAddress": "b@example.com"}]}},
        )

        # Assert
        self.assertContains(response, "{}", status_code=200)
        recipient = EmailRecipient.objects.get(email="b@example.com")
        self.assertTrue(recipient.do_not_email)

    def test_complaint_marks_do_not_email(self):
        # Act
        response = self._post_notification(
            "Complaint",
            {
                "complaint": {
                    "complainedRecipients": [{"emailAddress": "c@example.com"}]
                }
            },
        )

        # Assert
        self.assertContains(response, "{}", status_code=200)
        recipient = EmailRecipient.objects.get(email="c@example.com")
        self.assertTrue(recipient.do_not_email)
