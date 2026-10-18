from datetime import timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from mailing_list.services import EmailService
from user.models import User


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
        """Email eligible users whose accounts turned a week old in the last day."""
        week_ago = timezone.now() - timedelta(days=7)
        # The one-day window must match the daily beat task's interval.
        users = self._get_eligible_users().filter(
            date_joined__gt=week_ago - timedelta(days=1),
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
        """Claim the user's single send, then email them the edit-profile link."""
        claimed = User.objects.filter(
            id=user.id, complete_profile_email_sent_date__isnull=True
        ).update(complete_profile_email_sent_date=timezone.now())
        if not claimed:
            return
        self.email_service.send_email(
            user.email,
            "Finish your ResearchHub profile",
            {"profile_url": f"{user.frontend_view_link()}?edit_profile=true"},
            template="complete_profile_email",
        )
