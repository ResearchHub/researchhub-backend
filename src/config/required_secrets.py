import os
import secrets
import sys

from django.core.exceptions import ImproperlyConfigured

APPLICATION_SECRETS = ("SECRET_KEY", "SALT_KEY")
API_SECRETS = (
    "HEALTH_CHECK_TOKEN",
    "PERSONA_WEBHOOK_SECRET",
    "STRIPE_WEBHOOK_SIGNING_SECRET",
)
SAMPLE_VALUES = frozenset(
    {
        "NOT_REAL",
        "PLACEHOLDER",
        "development",
        "development-salt-key",
        "test",
        "test-salt-key",
    }
)
ASGI_APPLICATION = "researchhub.asgi:application"
CELERY_APP_ARGUMENTS = ["--app", "researchhub"]
CELERY_COMMANDS_WITHOUT_SECRETS = (["beat"], ["flower"])


def is_deployed():
    app_env = os.environ.get("APP_ENV") or "development"
    return "production" in app_env or "staging" in app_env


def _runs_without_secrets():
    program = os.path.basename(sys.argv[0])
    arguments = sys.argv[1:]
    if program == "manage.py":
        return arguments[:1] == ["collectstatic"]
    if program == "celery":
        return (
            arguments[:2] == CELERY_APP_ARGUMENTS
            and arguments[2:3] in CELERY_COMMANDS_WITHOUT_SECRETS
        )
    return False


def required_secrets():
    if not is_deployed() or _runs_without_secrets():
        return ()
    if ASGI_APPLICATION in sys.argv:
        return APPLICATION_SECRETS + API_SECRETS
    return APPLICATION_SECRETS


def _is_configured(name):
    value = os.environ.get(name, "").strip()
    return bool(value) and value not in SAMPLE_VALUES


def check_required_secrets():
    missing = [name for name in required_secrets() if not _is_configured(name)]
    if missing:
        raise ImproperlyConfigured(
            "Required environment variables are missing or set to a sample value "
            f"for APP_ENV={os.environ.get('APP_ENV')}: {', '.join(missing)}"
        )


def local_default(value):
    return secrets.token_urlsafe(50) if is_deployed() else value
