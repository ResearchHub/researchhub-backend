import json
from django.test import TransactionTestCase

from mailing_list.models import EmailRecipient
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import get_authenticated_post_response


class MailingListEmailTests(TransactionTestCase):
    def setUp(self):
        self.user = create_random_authenticated_user('mailing_user')
        self.bounced_email = 'bounce@quantfive.org'

    def test_bounce_notification_blacklists_email(self):
        url = '/email_notifications/'
        data = self.build_bounce_request_data()
        response = get_authenticated_post_response(
            self.user,
            url,
            data,
            content_type='plain/text'
        )
        self.assertContains(response, '{}', status_code=200)

        recipient = EmailRecipient.objects.get(email=self.bounced_email)
        self.assertTrue(recipient.do_not_email)

    def build_bounce_request_data(self):
        request_data = json.dumps({
            "Type": "Notification",
            "Message": json.dumps({
                "notificationType": "Bounce", "bounce": {
                    "bouncedRecipients": [
                        {"emailAddress": self.bounced_email}
                    ]
                }
            })
        })
        return request_data
