from django.test import TestCase

from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_default_user
)


class MailingListModelsTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user('mlm')

    def test_receives_notifications_is_false_if_bounced(self):
        user = create_random_default_user('Aaron')
        user.emailrecipient.bounced()
        self.assertFalse(user.emailrecipient.receives_notifications)

    def test_receives_notifications_is_false_if_opted_out(self):
        user = create_random_default_user('Baron')
        user.emailrecipient.set_opted_out(True)
        self.assertFalse(user.emailrecipient.receives_notifications)

    def test_receives_notifications_is_true_by_default(self):
        user = create_random_default_user('Caron')
        self.assertTrue(user.emailrecipient.receives_notifications)

    def test_receives_notifications_if_bounced_opted_out_and_subscribed(self):
        user = create_random_default_user('Daron')
        self.assertTrue(user.emailrecipient.receives_notifications)
        user.emailrecipient.set_opted_out(True)
        user.emailrecipient.bounced()
        self.assertFalse(user.emailrecipient.receives_notifications)
