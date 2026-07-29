from warnings import deprecated

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Trim
from django.utils import timezone


@deprecated("EmailRecipient is deprecated. Use EmailOptOut or SES blacklist.")
class EmailRecipient(models.Model):
    """
    This model is deprecated and it currently only kept for data migration purposes.
    """

    email = models.EmailField(unique=True)
    do_not_email = models.BooleanField(default=False)
    is_opted_out = models.BooleanField(default=False)
    user = models.OneToOneField(
        "user.User", on_delete=models.CASCADE, default=None, null=True
    )
    bounced_date = models.DateTimeField(default=None, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.email}"

    @classmethod
    def get_suppressed_emails(cls, emails: list[str]) -> set[str]:
        """Return the subset of *emails* that should not receive mail.

        An address is suppressed when it has ``do_not_email=True``
        (bounced / complained) or ``is_opted_out=True``.
        """
        return set(
            cls.objects.filter(
                Q(do_not_email=True) | Q(is_opted_out=True),
                email__in=emails,
            ).values_list("email", flat=True)
        )

    def bounced(self):
        self.bounced_date = timezone.now()
        self.do_not_email = True
        self.save()

    def set_opted_out(self, opt_out):
        self.is_opted_out = opt_out
        self.save()

    @property
    def receives_notifications(self):
        return not self.do_not_email and not self.is_opted_out


class EmailOptOut(models.Model):
    """
    An email address that has unsubscribed from notification emails.
    Rows in this table represent deliberate opt-out events by users.
    For transactional emails, such as password resets, the entries in this table should
    be ignored.

    Note: Bounces and complaints are handled separately by Django SES's blacklist.
    """

    email = models.EmailField(
        db_index=True, db_comment="Normalized to lowercase for matching."
    )
    opted_out_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="mailing_list_email_opt_out_email_lower_unique",
            ),
            models.CheckConstraint(
                condition=Q(email=Trim(Lower("email"))),
                name="mailing_list_email_opt_out_email_normalized",
            ),
        ]

    def __str__(self):
        return f"{self.email}"

    @classmethod
    def add(cls, email: str) -> bool:
        """
        Record an opt-out for the given `email`. Returns whether one was added.
        """
        normalized = cls._normalize(email)
        if not normalized:
            return False

        _, created = cls.objects.get_or_create(email=normalized)
        return created

    @classmethod
    def remove(cls, email: str) -> bool:
        """
        Remove the opt-out for the given `email`. Returns whether one was removed.
        """
        deleted, _ = cls.objects.filter(email=cls._normalize(email)).delete()
        return bool(deleted)

    @classmethod
    def filter_opted_out(cls, emails: list[str]) -> set[str]:
        """
        Return the subset of `emails` that are opted out.
        """
        matches = set(
            cls.objects.filter(
                email__in={cls._normalize(email) for email in emails}
            ).values_list("email", flat=True)
        )
        return {email for email in emails if cls._normalize(email) in matches}

    @staticmethod
    def _normalize(email: str | None) -> str:
        return (email or "").strip().lower()
