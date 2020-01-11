from django.test import TestCase
from django.core import mail

from mailing_list.tests.helpers import (
    create_thread_subscription,
    create_email_recipient
)
from mailing_list.tasks import get_subscribed_actions
from discussion.tests.helpers import create_comment, create_thread
from user.tests.helpers import create_user, create_random_default_user


class MailingListTasksTests(TestCase):
    def setUp(self):
        self.user = create_user(email='val@quantfive.org')
        self.thread_subscription = create_thread_subscription()

        self.email_recipient = create_email_recipient(
            user=self.user,
            thread_subscription=self.thread_subscription
        )

        self.user_thread = create_thread(created_by=self.user)

    def test_get_thread_comment_actions(self):
        rando = create_random_default_user('rando')
        create_comment(thread=self.user_thread, created_by=rando)
        cursor = 0
        actions, actions_by_type, next_cursor = get_subscribed_actions(
            self.user,
            cursor,
            self.thread_subscription
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual(len(mail.outbox), 1)
