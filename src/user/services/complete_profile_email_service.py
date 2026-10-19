from datetime import timedelta

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone

from mailing_list.services import EmailService
from user.models import User

ACCOUNT_AGE = timedelta(days=7)
CATCH_UP_WINDOW = timedelta(days=7)


class CompleteProfileEmailService:
    """Send the one-time email nudging users to finish their author profile."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        """Configure the email transport."""
        self.email_service = email_service or EmailService()

    def send_if_eligible(self, user_id: int) -> None:
        """Email the user if their profile is incomplete and not yet emailed."""
        user = self._get_eligible_users().filter(id=user_id).first()
        if user is not None:
            self._send(user)

    def send_to_week_old_accounts(self) -> None:
        """Email eligible users whose accounts are one to two weeks old."""
        week_ago = timezone.now() - ACCOUNT_AGE
        # The lower bound lets missed or failed runs catch up without emailing
        # every account that predates this feature.
        users = self._get_eligible_users().filter(
            date_joined__gt=week_ago - CATCH_UP_WINDOW,
            date_joined__lte=week_ago,
        )
        for user in users.iterator():
            self._send(user)

    def _get_eligible_users(self) -> QuerySet[User]:
        """Return users in good standing, not yet emailed, missing a profile field."""
        missing_field = Q()
        for field in (
            "profile_image",
            "orcid_id",
            "twitter",
            "linkedin",
            "google_scholar",
        ):
            lookup = f"author_profile__{field}"
            missing_field |= Q(**{f"{lookup}__isnull": True}) | Q(**{lookup: ""})
        return User.objects.filter(
            missing_field,
            is_active=True,
            is_suspended=False,
            probable_spammer=False,
            complete_profile_email_sent_date__isnull=True,
        ).select_related("author_profile")

    def _send(self, user: User) -> None:
        """Claim the user's single send, releasing it unless the email is accepted."""
        claimed_at = timezone.now()
        claimed = User.objects.filter(
            id=user.id, complete_profile_email_sent_date__isnull=True
        ).update(complete_profile_email_sent_date=claimed_at)
        if not claimed:
            return
        accepted = 0
        try:
            accepted = self.email_service.send_email(
                user.email,
                "Finish your ResearchHub profile",
                {
                    "profile_url": f"{settings.BASE_FRONTEND_URL}/author/"
                    f"{user.author_profile.id}"
                },
                template="complete_profile_email",
            )
        finally:
            if not accepted:
                User.objects.filter(
                    id=user.id, complete_profile_email_sent_date=claimed_at
                ).update(complete_profile_email_sent_date=None)
