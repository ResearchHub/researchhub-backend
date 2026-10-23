import string
import unittest
from unittest.mock import patch

import boto3
from django.test import TestCase

from utils.test_helpers import AWSMockTestCase, generate_password


class TestTestHelpers(TestCase):
    def test_generate_password(self):
        password = generate_password()
        self.assertEqual(len(password), 16)
        self.assertTrue(any(c.isalpha() for c in password))
        self.assertTrue(any(c.isdigit() for c in password))
        self.assertTrue(any(c in string.punctuation for c in password))

    def test_generate_password_with_custom_length(self):
        password = generate_password(length=3)
        self.assertEqual(len(password), 3)
        self.assertTrue(any(c.isalpha() for c in password))
        self.assertTrue(any(c.isdigit() for c in password))
        self.assertTrue(any(c in string.punctuation for c in password))


class AWSMockTestCaseTests(unittest.TestCase):
    def test_class_fixtures_and_tests_have_independent_aws_mocks(self):
        # Arrange
        fixture_clients = []
        test_clients = []

        class FixtureCase(AWSMockTestCase):
            databases = set()

            @classmethod
            def setUpTestData(cls):
                super().setUpTestData()
                client = boto3.Session().client("s3")
                client.get_object(Bucket="fixtures", Key="shared")
                fixture_clients.append(client)

            def test_client(self):
                client = boto3.Session().client("s3")
                self.assertIs(client, self.mock_aws_client)
                client.get_object.assert_not_called()
                client.get_object(Bucket="tests", Key="isolated")
                test_clients.append(client)

        suite = unittest.TestSuite(
            [FixtureCase("test_client"), FixtureCase("test_client")]
        )
        result = unittest.TestResult()

        # Act
        with patch.object(
            boto3.Session, "client", side_effect=AssertionError("Unmocked AWS client")
        ) as original_client:
            suite.run(result)

            # Assert
            self.assertIs(boto3.Session.client, original_client)
            original_client.assert_not_called()
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assertEqual(result.testsRun, 2)
        self.assertEqual(len(fixture_clients), 1)
        self.assertEqual(len(test_clients), 2)
        self.assertIsNot(test_clients[0], test_clients[1])
        for client in test_clients:
            self.assertIsNot(client, fixture_clients[0])

    def test_failed_class_fixtures_restore_aws_client_creation(self):
        # Arrange
        class BrokenFixtureCase(AWSMockTestCase):
            databases = set()

            @classmethod
            def setUpTestData(cls):
                boto3.Session().client("s3")
                raise RuntimeError("fixture setup failed")

            def test_client(self):
                self.fail("The failed fixture should prevent this test from running")

        suite = unittest.TestSuite([BrokenFixtureCase("test_client")])
        result = unittest.TestResult()

        # Act
        with patch.object(
            boto3.Session, "client", side_effect=AssertionError("Unmocked AWS client")
        ) as original_client:
            suite.run(result)

            # Assert
            self.assertIs(boto3.Session.client, original_client)
            original_client.assert_not_called()
        self.assertEqual(result.testsRun, 0)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("fixture setup failed", result.errors[0][1])
