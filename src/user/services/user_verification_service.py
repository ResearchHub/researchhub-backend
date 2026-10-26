from allauth.account.models import EmailAddress

from orcid.config import EDU_DOMAINS
from user.models import User

X_VERIFICATION_METHOD = "X"
EDU_EMAIL_VERIFICATION_METHOD = "EDU_EMAIL"


class UserVerificationService:
    """Service for reading the ways a user has verified themselves."""

    def list_verification_methods(self, user: User) -> list[str]:
        """List every way the user has verified themselves, in display order."""
        methods = []
        if user.has_approved_identity_verification():
            methods.append(user.userverification.verified_by)
        if user.has_x_verified_identity():
            methods.append(X_VERIFICATION_METHOD)
        if self._has_verified_edu_email(user):
            methods.append(EDU_EMAIL_VERIFICATION_METHOD)
        return methods

    def _has_verified_edu_email(self, user: User) -> bool:
        """Check whether the user's account or ORCID record has a verified edu email."""
        if user.author_profile.orcid_verified_edu_email:
            return True
        return (
            user.email.lower().endswith(EDU_DOMAINS)
            and EmailAddress.objects.filter(
                user=user, email__iexact=user.email, verified=True
            ).exists()
        )
