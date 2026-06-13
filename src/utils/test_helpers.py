import json
import secrets
import string
import threading
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from paper.models import Paper
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


def bytes_to_json(data_bytes):
    """Returns `json_dict` representation of `data_bytes`."""
    data_string = data_bytes.decode("utf-8")
    json_dict = json.loads(data_string)
    return json_dict


def get_authenticated_get_response(user, url, content_type="application/json"):
    """
    Sends a get request authenticated with `user` and returns the response.
    """
    client, content_format = _get_authenticated_client_config(user, url, content_type)

    response = client.get(url, format=content_format)
    return response


def get_get_response(
    path, query_data=None, follow_redirects=True, csrf=False, http_origin=None
):
    """
    Returns the response of a `GET` request made by `client`.

    query_data {'param1': ['value1', 'value2'], 'param2': ['value3']}
    """
    client = APIClient(enforce_csrf_checks=csrf, HTTP_ORIGIN=http_origin)
    return client.get(
        path, data=query_data, follow=follow_redirects, content_type="application/json"
    )


def get_authenticated_post_response(
    user, url, data, content_type="application/json", follow=False, headers=None
):
    """
    Sends a post request authenticated with `user` and returns the response.
    """
    client, content_format = _get_authenticated_client_config(
        user,
        url,
        content_type,
        http_origin=headers and headers.get("HTTP_ORIGIN", None),
    )
    response = client.post(url, data, format=content_format, follow=follow)
    return response


def get_authenticated_patch_response(user, url, data, content_type):
    """
    Sends a patch request authenticated with `user` and returns the response.
    """
    client, content_format = _get_authenticated_client_config(user, url, content_type)
    response = client.patch(url, data, format=content_format)
    return response


def get_authenticated_put_response(user, url, data, content_type="application/json"):
    """
    Sends a put request authenticated with `user` and returns the response.
    """
    client, content_format = _get_authenticated_client_config(user, url, content_type)
    response = client.put(url, data, format=content_format)
    return response


def get_authenticated_delete_response(user, url, data, content_type):
    """
    Sends a delete request authenticated with `user` and returns the response.
    """
    client, content_format = _get_authenticated_client_config(user, url, content_type)
    response = client.delete(url, data, format=content_format)
    return response


def _get_authenticated_client_config(user, url, content_type, http_origin=None):
    csrf = False

    if content_type == "multipart/form-data":
        content_format = "multipart"
        csrf = True
    elif content_type == "plain/text":
        content_format = "txt"
    else:
        content_format = "json"

    client = APIClient(enforce_csrf_checks=csrf, HTTP_ORIGIN=http_origin)
    client.force_authenticate(user=user, token=user.auth_token)
    return client, content_format


def get_user_from_response(response):
    return response.wsgi_request.user


class DatabaseThread(threading.Thread):
    def run(self):
        super().run()
        connection.close()


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


def create_test_paper(
    title="Test Paper",
    doi=None,
    paper_title=None,
    abstract="Test abstract",
    uploaded_by=None,
):
    """Create a test paper with the given parameters."""
    if uploaded_by is None:
        uploaded_by = create_test_user()
    if paper_title is None:
        paper_title = title

    return Paper.objects.create(
        title=title,
        paper_title=paper_title,
        doi=doi,
        abstract=abstract,
        uploaded_by=uploaded_by,
        paper_publish_date="2023-01-01",
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
