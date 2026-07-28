from django.test import TestCase

from mailing_list.models import EmailRecipient
from user.tests.helpers import create_random_default_user


class ReceivesNotificationsTests(TestCase):
    def test_true_when_neither_bounced_nor_opted_out(self):
        # Arrange
        recipient = EmailRecipient.objects.create(email="good@example.com")

        # Act
        result = recipient.receives_notifications

        # Assert
        self.assertTrue(result)

    def test_false_when_bounced(self):
        # Arrange
        recipient = EmailRecipient.objects.create(
            email="bounced@example.com", do_not_email=True
        )

        # Act
        result = recipient.receives_notifications

        # Assert
        self.assertFalse(result)

    def test_false_when_opted_out(self):
        # Arrange
        recipient = EmailRecipient.objects.create(
            email="optout@example.com", is_opted_out=True
        )

        # Act
        result = recipient.receives_notifications

        # Assert
        self.assertFalse(result)


class BouncedTests(TestCase):
    def test_marks_do_not_email_and_records_timestamp(self):
        # Arrange
        recipient = EmailRecipient.objects.create(email="bounced@example.com")

        # Act
        recipient.bounced()

        # Assert
        recipient.refresh_from_db()
        self.assertTrue(recipient.do_not_email)
        self.assertIsNotNone(recipient.bounced_date)


class SetOptedOutTests(TestCase):
    def test_opts_recipient_out(self):
        # Arrange
        recipient = EmailRecipient.objects.create(email="user@example.com")

        # Act
        recipient.set_opted_out(True)

        # Assert
        recipient.refresh_from_db()
        self.assertTrue(recipient.is_opted_out)

    def test_opts_recipient_back_in(self):
        # Arrange
        recipient = EmailRecipient.objects.create(
            email="user@example.com", is_opted_out=True
        )

        # Act
        recipient.set_opted_out(False)

        # Assert
        recipient.refresh_from_db()
        self.assertFalse(recipient.is_opted_out)


class GetSuppressedEmailsTests(TestCase):
    def test_returns_bounced_and_opted_out_emails(self):
        # Arrange
        EmailRecipient.objects.create(email="bounced@example.com", do_not_email=True)
        EmailRecipient.objects.create(email="optout@example.com", is_opted_out=True)
        EmailRecipient.objects.create(email="good@example.com")

        # Act
        result = EmailRecipient.get_suppressed_emails(
            ["bounced@example.com", "optout@example.com", "good@example.com"]
        )

        # Assert
        self.assertEqual(result, {"bounced@example.com", "optout@example.com"})

    def test_ignores_suppressed_addresses_outside_the_queried_list(self):
        # Arrange
        EmailRecipient.objects.create(email="bounced@example.com", do_not_email=True)

        # Act
        result = EmailRecipient.get_suppressed_emails(["good@example.com"])

        # Assert
        self.assertEqual(result, set())

    def test_returns_empty_set_for_unknown_emails(self):
        # Act
        result = EmailRecipient.get_suppressed_emails(["unknown@example.com"])

        # Assert
        self.assertEqual(result, set())

    def test_matches_a_stored_address_regardless_of_case(self):
        # Arrange
        EmailRecipient.objects.create(email="Mixed@Example.com", is_opted_out=True)

        # Act
        result = EmailRecipient.get_suppressed_emails(["mixed@example.com"])

        # Assert
        self.assertEqual(result, {"mixed@example.com"})

    def test_returns_the_caller_spelling_not_the_stored_one(self):
        # Arrange
        EmailRecipient.objects.create(email="lower@example.com", is_opted_out=True)

        # Act
        result = EmailRecipient.get_suppressed_emails(["LOWER@example.com"])

        # Assert
        self.assertEqual(result, {"LOWER@example.com"})

    def test_suppresses_every_casing_present_in_the_queried_list(self):
        # Arrange
        EmailRecipient.objects.create(email="dup@example.com", is_opted_out=True)

        # Act
        result = EmailRecipient.get_suppressed_emails(
            ["dup@example.com", "Dup@Example.com"]
        )

        # Assert
        self.assertEqual(result, {"dup@example.com", "Dup@Example.com"})

    def test_either_row_of_a_case_collision_pair_suppresses_the_address(self):
        # Arrange
        EmailRecipient.objects.create(email="pair@example.com")
        EmailRecipient.objects.create(email="Pair@Example.com", is_opted_out=True)

        # Act
        result = EmailRecipient.get_suppressed_emails(["pair@example.com"])

        # Assert
        self.assertEqual(result, {"pair@example.com"})


class UserRecipientSyncTests(TestCase):
    """``User.save()`` keeps an ``EmailRecipient`` in sync with the account."""

    def test_recipient_is_created_for_a_new_user(self):
        # Act
        user = create_random_default_user("sync")

        # Assert
        self.assertEqual(user.emailrecipient.email, user.email)
        self.assertTrue(user.emailrecipient.receives_notifications)

    def test_recipient_email_follows_the_user_email(self):
        # Arrange
        user = create_random_default_user("resync")
        recipient = user.emailrecipient

        # Act
        user.email = "changed@example.com"
        user.save()

        # Assert
        recipient.refresh_from_db()
        self.assertEqual(recipient.email, "changed@example.com")
        self.assertEqual(EmailRecipient.objects.filter(user=user).count(), 1)
