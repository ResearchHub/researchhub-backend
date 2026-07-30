from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from mailing_list.models import EmailOptOut


class InvalidUnsubscribeCodeError(ValueError):
    """Raised when an unsubscribe code is invalid."""


class EmailSubscriptionService:
    """
    Manage email subscription preferences and signed action codes.
    """

    def __init__(
        self,
        frontend_url: str | None = None,
    ):
        self._frontend_url = frontend_url or (
            f"{settings.BASE_FRONTEND_URL.rstrip('/')}/email/unsubscribe/"
        )

    def _generate_unsubscribe_code(self, email: str) -> str:
        """
        Return a signed unsubscribe code for the given email address.
        """
        normalized_email = self._validate_and_normalize_email(email)
        return signing.dumps(
            {"email": normalized_email},
            compress=True,
        )

    def generate_unsubscribe_url(self, email: str) -> str:
        """
        Return the frontend unsubscribe URL for the given email address.
        """
        code = self._generate_unsubscribe_code(email)
        parts = urlsplit(self._frontend_url)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key != "code"
        ]
        query.append(("code", code))
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    def _read_unsubscribe_code(self, code: str) -> str:
        """
        Return the normalized email address carried by a trusted code.
        """
        try:
            payload = signing.loads(code)
            if not isinstance(payload, dict):
                raise InvalidUnsubscribeCodeError("Invalid unsubscribe code")

            return self._validate_and_normalize_email(payload.get("email"))
        except (
            signing.BadSignature,
            ValidationError,
            TypeError,
            AttributeError,
        ) as error:
            raise InvalidUnsubscribeCodeError("Invalid unsubscribe code") from error

    def unsubscribe(self, code: str) -> bool:
        """
        Opt out the address carried by a signed code.

        Returns whether a new opt-out record was created.
        """
        email = self._read_unsubscribe_code(code)
        return EmailOptOut.add(email)

    @staticmethod
    def _validate_and_normalize_email(email: str | None) -> str:
        normalized_email = EmailOptOut._normalize(email)
        validate_email(normalized_email)
        return normalized_email
