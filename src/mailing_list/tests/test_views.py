import json

from django.test import TransactionTestCase

from mailing_list.models import EmailRecipient
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import get_authenticated_post_response


class MailingListSNSEmailTests(TransactionTestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("mailing_user")

    def _post_notification(self, notification_type, payload):
        # Arrange
        message = {"notificationType": notification_type, **payload}
        data = json.dumps({"Type": "Notification", "Message": json.dumps(message)})

        # Act
        return get_authenticated_post_response(
            self.user, "/email_notifications/", data, content_type="plain/text"
        )

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
