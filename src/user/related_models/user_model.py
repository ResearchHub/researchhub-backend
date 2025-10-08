import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from hub.models import Hub
from mailing_list.models import EmailRecipient
from reputation.models import Bounty, Distribution, PaidStatusModelMixin, Withdrawal
from researchhub.settings import ASSETS_BASE_URL, BASE_FRONTEND_URL, NO_ELASTIC
from researchhub_access_group.constants import (
    ASSISTANT_EDITOR,
    ASSOCIATE_EDITOR,
    SENIOR_EDITOR,
)
from user.tasks import update_elastic_registry
from utils.message import send_email_message
from utils.throttles import UserSustainedRateThrottle

FOUNDATION_EMAIL = "main@researchhub.foundation"
FOUNDATION_REVENUE_EMAIL = "revenue1@researchhub.foundation"


class UserManager(UserManager):
    def editors(self):
        editors = self.filter(
            (
                Q(permissions__access_type=ASSISTANT_EDITOR)
                | Q(permissions__access_type=ASSOCIATE_EDITOR)
                | Q(permissions__access_type=SENIOR_EDITOR)
            ),
            permissions__isnull=False,
            permissions__content_type=ContentType.objects.get_for_model(Hub),
        ).distinct()
        return editors

    def _get_default_account(self):
        user = User.objects.filter(email="bank@researchhub.com")
        if user.exists():
            return user.first()
        return User.objects.get(id=1)

    def get_revenue_account(self):
        user = User.objects.filter(email="revenue@researchhub.com")
        if user.exists():
            return user.first()

        return self._get_default_account()

    def get_community_account(self):
        user = User.objects.filter(email=FOUNDATION_EMAIL)
        if user.exists():
            return user.first()

        return self._get_default_account()

    def get_community_revenue_account(self):
        user = User.objects.filter(email=FOUNDATION_REVENUE_EMAIL)
        if user.exists():
            return user.first()

        return self._get_default_account()


"""
User objects have the following fields by default:
    https://docs.djangoproject.com/en/2.2/ref/contrib/auth/#django.contrib.auth.models.User
"""


class User(AbstractUser):
    agreed_to_terms = models.BooleanField(default=False)
    clicked_on_balance_date = models.DateTimeField(auto_now_add=True)
    country_code = models.CharField(max_length=4, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)

    # onboarding state
    has_seen_first_coin_modal = models.BooleanField(default=False)
    has_seen_orcid_connect_modal = models.BooleanField(default=False)
    has_completed_onboarding = models.BooleanField(default=False)

    invited_by = models.ForeignKey(
        "self", related_name="invitee", on_delete=models.SET_NULL, null=True, blank=True
    )
    is_suspended = models.BooleanField(default=False)
    moderator = models.BooleanField(default=False)
    probable_spammer = models.BooleanField(default=False)
    referral_code = models.CharField(max_length=36, default=uuid.uuid4, unique=True)
    reputation = models.IntegerField(default=100)
    should_display_rsc_balance_home = models.BooleanField(default=True)
    spam_updated_date = models.DateTimeField(null=True)
    suspended_updated_date = models.DateTimeField(null=True)
    updated_date = models.DateTimeField(auto_now=True)
    upload_tutorial_complete = models.BooleanField(default=False)

    # Official accounts are currently used as a distinguishing factor in bounties.
    # Bounties are separated into two categories: official and community.
    is_official_account = models.BooleanField(default=False)

    objects = UserManager()

    def full_name(self):
        return self.first_name + " " + self.last_name

    def __str__(self):
        return f"{self.id}: {self.first_name} {self.last_name}"

    class Meta:
        ordering = ["-created_date"]
        indexes = [
            models.Index(
                fields=["is_active", "is_suspended", "probable_spammer"],
                name="user_active_spam_idx",
                condition=Q(is_active=True, is_suspended=False, probable_spammer=False),
            ),
        ]

    def save(self, *args, **kwargs):
        # A unique constraint is enforced on the username on the database
        # level. This line is used to ensure usernames are not empty without
        # requiring the client to enter a value in this field. It also forces
        # emails to be unique.
        #
        # If we want to allow client specified usernames, simply remove the
        # set username line.

        if (self.email is not None) and (self.email != ""):
            self.username = self.email

        user_to_save = super(User, self).save(*args, **kwargs)

        # Keep Email Recipient up to date with email
        if (self.email is not None) and (self.email != ""):
            if hasattr(self, "emailrecipient") and (self.emailrecipient is not None):
                if self.emailrecipient.email != self.email:
                    er = self.emailrecipient
                    er.email = self.email
                    er.save()
            else:
                EmailRecipient.objects.create(user=self, email=self.email)

        # Update the Elastic Search index
        if not NO_ELASTIC:
            try:
                update_elastic_registry.apply_async([self.id])
            except Exception:
                pass

        return user_to_save

    def set_has_seen_first_coin_modal(self, has_seen):
        self.has_seen_first_coin_modal = has_seen
        self.save()

    def set_has_seen_orcid_connect_modal(self, has_seen):
        self.has_seen_orcid_connect_modal = has_seen
        self.save()

    def set_probable_spammer(self, probable_spammer=True):
        if self.probable_spammer != probable_spammer:
            capcha_throttle = UserSustainedRateThrottle()
            capcha_throttle.lock(self, "probably_spam")

            self.probable_spammer = probable_spammer
            self.spam_updated_date = timezone.now()
            self.save(update_fields=["probable_spammer", "spam_updated_date"])

    def set_suspended(self, is_suspended=True, is_manual=True):
        if self.is_suspended != is_suspended:
            self.is_suspended = is_suspended
            self.suspended_updated_date = timezone.now()
            self.save(update_fields=["is_suspended", "suspended_updated_date"])


    def get_balance_qs(self):
        user_balance = self.balances.all()
        if not user_balance:
            return self.balances.none()

        failed_withdrawals = self.withdrawals.filter(
            Q(paid_status=PaidStatusModelMixin.FAILED)
        ).values_list("id")

        balance = self.balances.exclude(
            content_type=ContentType.objects.get_for_model(Withdrawal),
            object_id__in=failed_withdrawals,
        )
        return balance

    def get_balance(self, queryset=None, include_locked=False):
        if queryset is None:
            queryset = self.get_balance_qs()

        # By default, exclude locked funds unless explicitly requested
        if not include_locked:
            queryset = queryset.filter(is_locked=False)

        balance = queryset.aggregate(
            total_balance=Coalesce(
                Sum(Cast("amount", DecimalField(max_digits=255, decimal_places=128))),
                Value(0),
                output_field=DecimalField(),
            )
        )
        total_balance = balance.get("total_balance", 0) or 0

        return total_balance

    def get_available_balance(self, queryset=None):
        """Returns balance excluding locked amounts"""
        if queryset is None:
            queryset = self.get_balance_qs()

        # Exclude locked balances from available balance
        available_queryset = queryset.filter(is_locked=False)
        return self.get_balance(queryset=available_queryset, include_locked=True)

    def get_locked_balance(self, lock_type=None):
        """Returns total locked balance amount, optionally filtered by lock_type"""
        locked_queryset = self.get_balance_qs().filter(is_locked=True)
        if lock_type:
            locked_queryset = locked_queryset.filter(lock_type=lock_type)
        return self.get_balance(queryset=locked_queryset, include_locked=True)

    def notify_inactivity(self, paper_count=0, comment_count=0):
        recipient = [self.email]
        subject = "[Editor] Weekly Inactivity"
        email_context = {
            "assets_base_url": ASSETS_BASE_URL,
            "name": f"{self.first_name} {self.last_name}",
            "paper_count": paper_count,
            "comment_count": comment_count,
        }
        send_email_message(
            recipient,
            "editor_inactivity.txt",
            subject,
            email_context,
            "editor_inactivity.html",
        )

    def is_hub_editor(self):
        hub_content_type = ContentType.objects.get_for_model(Hub)
        return self.permissions.filter(
            (
                Q(access_type=ASSISTANT_EDITOR)
                | Q(access_type=ASSOCIATE_EDITOR)
                | Q(access_type=SENIOR_EDITOR)
            ),
            content_type=hub_content_type,
        ).exists()

    def is_hub_editor_of(self, hubs):
        hub_content_type = ContentType.objects.get_for_model(Hub)
        return self.permissions.filter(
            (
                Q(access_type=ASSISTANT_EDITOR)
                | Q(access_type=ASSOCIATE_EDITOR)
                | Q(access_type=SENIOR_EDITOR)
            ),
            content_type=hub_content_type,
            object_id__in=hubs.values_list("id", flat=True),
        ).exists()

    def frontend_view_link(self):
        return f"{BASE_FRONTEND_URL}/user/{self.author_profile.id}/overview"

    def calculate_hub_scores(self):
        author = self.author_profile

        author.calculate_hub_scores()

    @property
    def upvote_count(self):
        from discussion.models import Vote

        upvote_count = (
            Distribution.objects.filter(
                recipient=self,
                proof_item_content_type=ContentType.objects.get_for_model(Vote),
                reputation_amount=1,
            ).aggregate(count=Count("id"))["count"]
            or 0
        )

        return upvote_count

    @property
    def amount_funded(self):
        amount_funded = (
            Bounty.objects.filter(
                created_by=self,
                status=Bounty.CLOSED,
            ).aggregate(
                total_amount=Sum("amount")
            )["total_amount"]
            or 0
        )

        return amount_funded

    @property
    def is_verified(self):
        """
        Check if the user account is verified.
        Returns `False` if the user was not successfully verified or
        if no verification record exists.
        """
        try:
            return self.userverification.is_verified
        except Exception:
            return False

    @property
    def peer_review_count(self):
        from researchhub_comment.related_models.rh_comment_model import RhCommentModel

        peer_review_count = RhCommentModel.objects.filter(
            created_by=self,
            comment_type="REVIEW",
            is_removed=False,
        ).aggregate(count=Count("id"))["count"]

        return peer_review_count
