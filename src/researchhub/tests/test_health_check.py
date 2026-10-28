from unittest import TestCase as UnitTestCase
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from researchhub.health_check import GitHashHealthCheck


class HealthCheckViewTests(TestCase):
    @patch.object(GitHashHealthCheck, "_get_git_hash", return_value="abc1234def5678")
    def test_runs_configured_checks(self, _):
        # Act
        response = self.client.get(
            reverse("health_check"), HTTP_ACCEPT="application/json"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "Cache(alias='default')": "OK",
                "Database(alias='default')": "OK",
                "GitHashHealthCheck(git_hash='abc1234')": "OK",
            },
        )


class GitHashTests(UnitTestCase):
    @patch.object(GitHashHealthCheck, "_read_git_hash_from_process")
    @patch.object(
        GitHashHealthCheck, "_read_git_hash_from_file", return_value="abc1234def5678"
    )
    def test_reads_hash_from_file(self, _, mock_process):
        # Arrange
        check = GitHashHealthCheck()

        # Act
        check.run()

        # Assert
        self.assertEqual(check.git_hash, "abc1234")
        mock_process.assert_not_called()

    @patch.object(
        GitHashHealthCheck, "_read_git_hash_from_process", return_value="fed4321cba"
    )
    @patch.object(GitHashHealthCheck, "_read_git_hash_from_file", return_value=None)
    def test_falls_back_to_git_process(self, *_):
        # Arrange
        check = GitHashHealthCheck()

        # Act
        check.run()

        # Assert
        self.assertEqual(check.git_hash, "fed4321")

    @patch.object(GitHashHealthCheck, "_read_git_hash_from_process", return_value=None)
    @patch.object(GitHashHealthCheck, "_read_git_hash_from_file", return_value=None)
    def test_unknown_without_hash(self, *_):
        # Arrange
        check = GitHashHealthCheck()

        # Act
        check.run()

        # Assert
        self.assertEqual(check.git_hash, "unknown")
