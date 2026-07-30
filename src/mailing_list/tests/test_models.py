from django.db.utils import IntegrityError
from django.test import TestCase

from mailing_list.models import EmailOptOut, EmailRecipient


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


class NormalizeTests(TestCase):
    def test_lowercases_and_strips(self):
        # Act
        result = EmailOptOut._normalize("  Foo@Example.COM ")

        # Assert
        self.assertEqual(result, "foo@example.com")


class SaveTests(TestCase):
    def test_normalizes_the_address(self):
        # Act
        opt_out = EmailOptOut.objects.create(email="  Foo@Example.COM ")

        # Assert
        opt_out.refresh_from_db()
        self.assertEqual(opt_out.email, "foo@example.com")


class AddTests(TestCase):
    def test_creates_a_normalized_row(self):
        # Act
        created = EmailOptOut.add("Foo@Example.com")

        # Assert
        self.assertTrue(created)
        self.assertEqual(EmailOptOut.objects.get().email, "foo@example.com")

    def test_is_idempotent_across_casing(self):
        # Arrange
        EmailOptOut.add("foo@example.com")

        # Act
        created = EmailOptOut.add("FOO@EXAMPLE.COM")

        # Assert
        self.assertFalse(created)
        self.assertEqual(EmailOptOut.objects.count(), 1)

    def test_ignores_a_blank_address(self):
        # Act
        created = EmailOptOut.add("   ")

        # Assert
        self.assertFalse(created)
        self.assertEqual(EmailOptOut.objects.count(), 0)

    def test_database_rejects_a_case_variant_duplicate(self):
        # Arrange
        EmailOptOut.objects.create(email="foo@example.com")

        # Act & Assert
        with self.assertRaises(IntegrityError):
            EmailOptOut.objects.create(email="FOO@example.com")


class RemoveTests(TestCase):
    def test_removes_the_row_regardless_of_casing(self):
        # Arrange
        EmailOptOut.add("foo@example.com")

        # Act
        deleted = EmailOptOut.remove("Foo@Example.com")

        # Assert
        self.assertTrue(deleted)
        self.assertEqual(EmailOptOut.objects.count(), 0)

    def test_is_a_no_op_for_an_unknown_address(self):
        # Act
        deleted = EmailOptOut.remove("nobody@example.com")

        # Assert
        self.assertFalse(deleted)


class FilterOptedOutTests(TestCase):
    def test_returns_only_opted_out_addresses(self):
        # Arrange
        EmailOptOut.add("optout@example.com")

        # Act
        result = EmailOptOut.filter_opted_out(
            ["optout@example.com", "good@example.com"],
        )

        # Assert
        self.assertEqual(result, {"optout@example.com"})

    def test_matches_regardless_of_the_casing_supplied(self):
        # Arrange
        EmailOptOut.add("optout@example.com")

        # Act
        result = EmailOptOut.filter_opted_out(["OptOut@Example.com"])

        # Assert: the caller gets its own string back, not the stored one
        self.assertEqual(result, {"OptOut@Example.com"})

    def test_returns_every_variant_of_the_same_address(self):
        # Arrange
        EmailOptOut.add("optout@example.com")

        # Act
        result = EmailOptOut.filter_opted_out(
            ["optout@example.com", "OptOut@Example.com"],
        )

        # Assert
        self.assertEqual(result, {"optout@example.com", "OptOut@Example.com"})

    def test_returns_an_empty_set_when_nothing_matches(self):
        # Act
        result = EmailOptOut.filter_opted_out(["unknown@example.com"])

        # Assert
        self.assertEqual(result, set())

    def test_matches_rows_created_outside_add(self):
        # Arrange: the admin, a shell, or a data migration bypasses `add`
        EmailOptOut.objects.create(email="OptOut@Example.com")

        # Act
        result = EmailOptOut.filter_opted_out(["optout@example.com"])

        # Assert
        self.assertEqual(result, {"optout@example.com"})
