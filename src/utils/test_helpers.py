import secrets
import string
from unittest.mock import MagicMock, patch

from django.test import TestCase, TransactionTestCase

from user.models import User


def generate_password(length=16):
    """
    Generates a password with at least one letter, one digit and one special character.
    """
    special_chars = "!@#$%^&*?"

    return "".join(
        secrets.choice(string.ascii_letters)  # 1 letter
        + secrets.choice(string.digits)  # 1 digit
        + secrets.choice(special_chars)  # 1 special char
        + "".join(
            secrets.choice(string.ascii_letters + string.digits + special_chars)
            for _ in range(length - 3)
        )
    )


def create_test_user(
    first_name="Test",
    last_name="User",
    email="test@example.com",
    password=generate_password(),
):
    """Create a test user with the given parameters."""
    return User.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        password=password,
    )


class AWSMockMixin:
    """
    A mixin that automatically mocks AWS client creation.

    This prevents tests from making real AWS API calls and speeds up test execution.
    The mock client is available as `self.mock_aws_client` for assertions.

    Usage:
        class MyTest(AWSMockMixin, TestCase):
            def test_something(self):
                # AWS calls are automatically mocked
                # Access the mock via self.mock_aws_client
                pass

        # For transaction tests:
        class MyTransactionTest(AWSMockMixin, TransactionTestCase):
            pass
    """

    def setUp(self):
        super().setUp()
        self.mock_aws_client = MagicMock()
        # Patch boto3.Session.client to catch all AWS client creation
        self.aws_patcher = patch(
            "boto3.Session.client", return_value=self.mock_aws_client
        )
        self.mock_boto3_client = self.aws_patcher.start()

    def tearDown(self):
        if hasattr(self, "aws_patcher"):
            self.aws_patcher.stop()
        super().tearDown()


# Convenience classes for common use cases
class AWSMockTestCase(AWSMockMixin, TestCase):
    """TestCase with AWS mocking. For most tests."""

    pass


class AWSMockTransactionTestCase(AWSMockMixin, TransactionTestCase):
    """TransactionTestCase with AWS mocking. For tests needing on_commit hooks."""

    pass
