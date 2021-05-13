import decimal
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from mailing_list.models import EmailRecipient
from user.tasks import handle_spam_user_task
from utils.siftscience import decisions_api
from utils.throttles import UserSustainedRateThrottle


"""
User objects have the following fields by default:
    https://docs.djangoproject.com/en/2.2/ref/contrib/auth/#django.contrib.auth.models.User
"""


class User(AbstractUser):
    country_code = models.CharField(max_length=4, null=True, blank=True)
    reputation = models.IntegerField(default=100)
    upload_tutorial_complete = models.BooleanField(default=False)
    has_seen_first_coin_modal = models.BooleanField(default=False)
    has_seen_orcid_connect_modal = models.BooleanField(default=False)
    has_seen_stripe_modal = models.BooleanField(default=False)
    agreed_to_terms = models.BooleanField(default=False)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    bookmarks = models.ManyToManyField(
        'paper.Paper',
        related_name='users_who_bookmarked'
    )
    moderator = models.BooleanField(default=False)
    is_suspended = models.BooleanField(default=False)
    probable_spammer = models.BooleanField(default=False)
    suspended_updated_date = models.DateTimeField(null=True)
    spam_updated_date = models.DateTimeField(null=True)
    referral_code = models.CharField(
        max_length=36,
        default=uuid.uuid4,
        unique=True
    )
    invited_by = models.ForeignKey(
        'self',
        related_name='invitee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    sift_risk_score = models.FloatField(null=True, blank=True)

    def full_name(self):
        return self.first_name + ' ' + self.last_name

    def __str__(self):
        return '{} / {}'.format(
            self.email,
            self.first_name + ' ' + self.last_name
        )

    class Meta:
        ordering = ['-created_date']

    def save(self, *args, **kwargs):
        # A unique constraint is enforced on the username on the database
        # level. This line is used to ensure usernames are not empty without
        # requiring the client to enter a value in this field. It also forces
        # emails to be unique.
        #
        # If we want to allow client specified usernames, simply remove the
        # set username line.

        if (self.email is not None) and (self.email != ''):
            self.username = self.email

        user_to_save = super(User, self).save(*args, **kwargs)

        # Keep Email Recipient up to date with email
        if (self.email is not None) and (self.email != ''):
            if hasattr(self, 'emailrecipient') and (
                self.emailrecipient is not None
            ):
                if self.emailrecipient.email != self.email:
                    er = self.emailrecipient
                    er.email = self.email
                    er.save()
            else:
                EmailRecipient.objects.create(user=self, email=self.email)

        return user_to_save

    def set_has_seen_first_coin_modal(self, has_seen):
        self.has_seen_first_coin_modal = has_seen
        self.save()

    def set_has_seen_orcid_connect_modal(self, has_seen):
        self.has_seen_orcid_connect_modal = has_seen
        self.save()

    def set_has_seen_stripe_modal(self, has_seen):
        self.has_seen_stripe_modal = has_seen
        self.save()

    def set_probable_spammer(self, probable_spammer=True):
        if self.probable_spammer != probable_spammer:
            capcha_throttle = UserSustainedRateThrottle()
            capcha_throttle.lock(self, "probably_spam")

            self.probable_spammer = probable_spammer
            self.spam_updated_date = timezone.now()
            self.save(update_fields=['probable_spammer', 'spam_updated_date'])

        if probable_spammer:
            handle_spam_user_task.apply_async((self.id,), priority=3)

    def set_suspended(self, is_suspended=True, is_manual=True):
        if self.is_suspended != is_suspended:
            self.is_suspended = is_suspended
            self.suspended_updated_date = timezone.now()
            self.save(update_fields=['is_suspended', 'suspended_updated_date'])

        if is_suspended:
            source = 'MANUAL_REVIEW' if is_manual else 'AUTOMATED_RULE'
            decisions_api.apply_bad_user_decision(self, source)

    def get_balance(self):
        user_balance = self.balances.all()
        if not user_balance:
            return 0

        # TODO: Could this be faster if we do it on the db level? Could we run
        # into a memory error here?
        balance = self.balances.values_list('amount', flat=True)
        balance_decimal = map(decimal.Decimal, balance)
        total_balance = sum(balance_decimal)
        return total_balance
