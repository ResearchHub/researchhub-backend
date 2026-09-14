from typing import override

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Trim
from django.utils import timezone


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

    @override
    def save(self, *args, **kwargs):
        # Normalize email so that stored rows match how they are looked up.
        self.email = self._normalize(self.email)
        super().save(*args, **kwargs)

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
