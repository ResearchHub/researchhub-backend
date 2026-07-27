from django.db import models
from django.db.models import Q
from django.utils import timezone


class EmailRecipient(models.Model):
    """Tracks an email address and whether it should receive mail."""

    email = models.EmailField(unique=True)
    do_not_email = models.BooleanField(default=False)
    is_opted_out = models.BooleanField(default=False)
    next_cursor = models.IntegerField(default=0)
    user = models.OneToOneField(
        "user.User", on_delete=models.CASCADE, default=None, null=True
    )
    bounced_date = models.DateTimeField(default=None, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

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

    def __str__(self):
        return f"{self.email}"

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
