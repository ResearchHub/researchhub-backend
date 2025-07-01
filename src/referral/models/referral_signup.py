from django.db import models

from user.models import User
from utils.models import DefaultModel


class ReferralSignup(DefaultModel):
    """
    Simple model to track when users sign up via referral links
    """

    referrer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="referrals_made",
        help_text="User who made the referral",
    )

    referred = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="referral_signup",
        help_text="User who signed up via referral",
    )

    signup_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["referrer", "signup_date"]),
        ]

    def __str__(self):
        return f"{self.referrer.email} referred {self.referred.email}"
