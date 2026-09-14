from django.db.utils import IntegrityError
from django.test import TestCase

from mailing_list.models import EmailOptOut


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
