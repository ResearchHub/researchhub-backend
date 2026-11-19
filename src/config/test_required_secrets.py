import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured

from config.required_secrets import (
    API_SECRETS,
    APPLICATION_SECRETS,
    check_required_secrets,
    local_default,
    required_secrets,
)

CONFIG_DIR = Path(__file__).resolve().parent
KEYS_FILES = (CONFIG_DIR / "keys.py", CONFIG_DIR / "ci" / "keys.py")

API_ARGV = ["/opt/venv/bin/uvicorn", "--port", "8000", "researchhub.asgi:application"]
WORKER_ARGV = ["/opt/venv/bin/celery", "--app", "researchhub", "worker"]
BEAT_ARGV = ["/opt/venv/bin/celery", "--app", "researchhub", "beat"]
FLOWER_ARGV = ["/opt/venv/bin/celery", "--app", "researchhub", "flower"]
MIGRATE_ARGV = ["manage.py", "migrate", "--noinput"]
COLLECTSTATIC_ARGV = ["manage.py", "collectstatic", "--noinput"]

APPLICATION_VALUES = {name: f"configured-{name}" for name in APPLICATION_SECRETS}
ALL_VALUES = {name: f"configured-{name}" for name in APPLICATION_SECRETS + API_SECRETS}


@contextmanager
def process(argv, **environ):
    with patch.object(sys, "argv", argv), patch.dict(os.environ, environ, clear=True):
        yield


def load_keys(path):
    namespace = {"__name__": "keys"}
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    return namespace


class RequiredSecretsTests(TestCase):
    def test_api_requires_application_and_api_secrets(self):
        for app_env in ("production", "staging"):
            with self.subTest(app_env=app_env), process(API_ARGV, APP_ENV=app_env):
                # Act
                result = required_secrets()

                # Assert
                self.assertEqual(result, APPLICATION_SECRETS + API_SECRETS)

    def test_worker_and_migration_require_application_secrets(self):
        for argv in (WORKER_ARGV, MIGRATE_ARGV):
            with self.subTest(argv=argv), process(argv, APP_ENV="production"):
                # Act
                result = required_secrets()

                # Assert
                self.assertEqual(result, APPLICATION_SECRETS)

    def test_processes_without_secrets_require_nothing(self):
        for argv in (BEAT_ARGV, FLOWER_ARGV, COLLECTSTATIC_ARGV):
            with self.subTest(argv=argv), process(argv, APP_ENV="production"):
                # Act
                result = required_secrets()

                # Assert
                self.assertEqual(result, ())

    def test_exemptions_match_only_the_exact_command(self):
        # Arrange
        commands = (
            ["/opt/venv/bin/celery", "--app", "researchhub", "worker", "beat"],
            ["/opt/venv/bin/celery", "--app", "other", "beat"],
            ["manage.py", "shell", "collectstatic"],
            ["/opt/venv/bin/python", "collectstatic"],
        )

        for argv in commands:
            with self.subTest(argv=argv), process(argv, APP_ENV="production"):
                # Act
                result = required_secrets()

                # Assert
                self.assertEqual(result, APPLICATION_SECRETS)

    def test_other_environments_require_nothing(self):
        for app_env in ("", "development", "test"):
            with self.subTest(app_env=app_env), process(API_ARGV, APP_ENV=app_env):
                # Act
                result = required_secrets()

                # Assert
                self.assertEqual(result, ())


class CheckRequiredSecretsTests(TestCase):
    def test_lists_every_missing_name_without_values(self):
        # Arrange
        environ = {"APP_ENV": "production", "SECRET_KEY": "configured-value"}

        # Act
        with (
            process(API_ARGV, **environ),
            self.assertRaises(ImproperlyConfigured) as raised,
        ):
            check_required_secrets()

        # Assert
        message = str(raised.exception)
        self.assertEqual(
            message.rsplit(": ", 1)[1].split(", "), ["SALT_KEY", *API_SECRETS]
        )
        self.assertNotIn("configured-value", message)

    def test_rejects_blank_and_sample_values(self):
        for value in ("", "   ", "development", "test", "PLACEHOLDER"):
            # Arrange
            environ = {**APPLICATION_VALUES, "APP_ENV": "staging", "SECRET_KEY": value}

            # Act & Assert
            with (
                self.subTest(value=value),
                process(WORKER_ARGV, **environ),
                self.assertRaisesRegex(ImproperlyConfigured, "SECRET_KEY"),
            ):
                check_required_secrets()

    def test_passes_when_all_secrets_are_set(self):
        # Arrange
        environ = {**ALL_VALUES, "APP_ENV": "production"}

        with process(API_ARGV, **environ):
            # Act & Assert
            check_required_secrets()

    def test_development_passes_without_secrets(self):
        with process(API_ARGV):
            # Act & Assert
            check_required_secrets()


class LocalDefaultTests(TestCase):
    def test_development_uses_the_given_value(self):
        with process(MIGRATE_ARGV, APP_ENV="development"):
            # Act
            result = local_default("development")

        # Assert
        self.assertEqual(result, "development")

    def test_deployed_never_uses_the_given_value(self):
        with process(BEAT_ARGV, APP_ENV="production"):
            # Act
            first = local_default("development")
            second = local_default("development")

        # Assert
        self.assertNotEqual(first, "development")
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 50)


class KeysModuleTests(TestCase):
    def test_deployed_process_stops_when_secret_is_missing(self):
        for path in KEYS_FILES:
            # Act & Assert
            with (
                self.subTest(path=str(path)),
                process(WORKER_ARGV, APP_ENV="production"),
                self.assertRaisesRegex(ImproperlyConfigured, "SECRET_KEY"),
            ):
                load_keys(path)

    def test_deployed_process_reads_configured_secrets(self):
        # Arrange
        environ = {**APPLICATION_VALUES, "APP_ENV": "production"}

        for path in KEYS_FILES:
            with self.subTest(path=str(path)), process(WORKER_ARGV, **environ):
                # Act
                keys = load_keys(path)

                # Assert
                self.assertEqual(keys["SECRET_KEY"], "configured-SECRET_KEY")
                self.assertEqual(keys["SALT_KEY"], "configured-SALT_KEY")

    def test_process_without_secrets_gets_no_sample_value(self):
        for path in KEYS_FILES:
            with self.subTest(path=str(path)):
                with process(BEAT_ARGV, APP_ENV="production"):
                    # Act
                    keys = load_keys(path)

                # Assert
                self.assertNotIn(keys["SECRET_KEY"], ("development", "test"))
                self.assertNotIn(
                    keys["SALT_KEY"], ("development-salt-key", "test-salt-key")
                )

    def test_development_keeps_local_defaults(self):
        for path in KEYS_FILES:
            with self.subTest(path=str(path)):
                with process(MIGRATE_ARGV, APP_ENV="development"):
                    # Act
                    keys = load_keys(path)

                # Assert
                self.assertIn(keys["SECRET_KEY"], ("development", "test"))
                self.assertIn(
                    keys["SALT_KEY"], ("development-salt-key", "test-salt-key")
                )
