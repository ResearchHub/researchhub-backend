"""Public academic email signal that never exposes the address itself."""

from typing import TypedDict

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.provider import GoogleProvider
from allauth.socialaccount.providers.orcid.provider import OrcidProvider

from user.constants.academic_email_constants import RESTRICTED_EDU_DOMAINS
from user.related_models.user_model import User

ORCID_SOURCE = "orcid"
ACCOUNT_EMAIL_SOURCE = "account_email"


class AcademicEmailBadge(TypedDict):
    email_domain: str
    institution_domain: str
    source: str


def _academic_badge(email: str, source: str) -> AcademicEmailBadge | None:
    """Describe an academic email without the address itself, e.g.
    "jdoe@cs.purdue.edu" -> email_domain "cs.purdue.edu" and institution_domain
    "purdue.edu". Returns None if the email isn't academic."""
    if "@" not in email:
        return None
    email_domain = email.rsplit("@", 1)[1].strip().lower()
    for suffix in RESTRICTED_EDU_DOMAINS:
        if email_domain.endswith(suffix):
            institution = email_domain.removesuffix(suffix).rsplit(".", 1)[-1]
            if not institution:
                return None
            return AcademicEmailBadge(
                email_domain=email_domain,
                institution_domain=f"{institution}{suffix}",
                source=source,
            )
    return None


def _is_google_verified(account: SocialAccount, email: str) -> bool:
    data = account.extra_data or {}
    google_email = data.get("email") or ""
    # Google accounts can be created on addresses the owner never verified.
    verified = data.get("email_verified") or data.get("verified_email")
    return bool(verified) and google_email.lower() == email.lower()


class AcademicEmailService:
    """Derives the verified academic email badge shown on public profiles."""

    def get_verified_academic_email(self, user: User) -> AcademicEmailBadge | None:
        """Return the badge for the user's verified academic email, preferring
        ORCID-verified emails over the login email."""
        accounts = list(
            SocialAccount.objects.filter(
                user=user, provider__in=(OrcidProvider.id, GoogleProvider.id)
            )
        )

        for account in accounts:
            if account.provider != OrcidProvider.id:
                continue
            for email in account.extra_data.get("verified_edu_emails", []):
                if badge := _academic_badge(email, ORCID_SOURCE):
                    return badge

        badge = _academic_badge(user.email, ACCOUNT_EMAIL_SOURCE)
        if badge and self._is_login_email_verified(user, accounts):
            return badge

        return None

    def _is_login_email_verified(
        self, user: User, accounts: list[SocialAccount]
    ) -> bool:
        if any(
            _is_google_verified(account, user.email)
            for account in accounts
            if account.provider == GoogleProvider.id
        ):
            return True
        return EmailAddress.objects.filter(
            user=user, email__iexact=user.email, verified=True
        ).exists()
