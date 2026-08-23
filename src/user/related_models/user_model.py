import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Cast, Coalesce, Lower
from django.utils import timezone

from hub.models import Hub
from purchase.related_models.balance_model import Balance
from reputation.models import PaidStatusModelMixin, Withdrawal
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_access_group.constants import (
    ASSISTANT_EDITOR,
    ASSOCIATE_EDITOR,
    SENIOR_EDITOR,
)
from utils.managers import SoftDeletableManagerMixin
from utils.models import SoftDeletableModel
from utils.throttles import UserSustainedRateThrottle

FOUNDATION_EMAIL = "main@researchhub.foundation"
FOUNDATION_REVENUE_EMAIL = "revenue1@researchhub.foundation"
AI_EXPERT_EMAIL = "ai-review@researchhub.foundation"


@dataclass(frozen=True)
class UnlockedBalanceLot:
    amount: Decimal
    created_date: date


class UserManager(SoftDeletableManagerMixin, DjangoUserManager):
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

    def get_ai_expert_account(self):
        user = self.filter(email=AI_EXPERT_EMAIL)
        if user.exists():
            return user.first()
        return None


"""
User objects have the following fields by default:
    https://docs.djangoproject.com/en/2.2/ref/contrib/auth/#django.contrib.auth.models.User
"""


class User(SoftDeletableModel, AbstractUser):
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
    is_staking_opted_in = models.BooleanField(default=True, db_index=True)
    staking_opted_in_date = models.DateTimeField(
        null=True, blank=True, default=timezone.now
    )
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

    @classmethod
    def is_rh_community_account(cls, user) -> bool:
        try:
            community_account = cls.objects.get_community_account()
        except Exception:
            return False
        return user.id == community_account.id

    @property
    def is_orcid_connected(self):
        if author := getattr(self, "author_profile", None):
            return author.is_orcid_connected
        return False

    @property
    def orcid_verified_edu_email(self):
        if author := getattr(self, "author_profile", None):
            return author.orcid_verified_edu_email
        return None

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
            models.Index(
                Lower("email"),
                name="user_email_lower_idx",
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        # A unique constraint is enforced on the username on the database
        # level. This line is used to ensure usernames are not empty without
        # requiring the client to enter a value in this field. It also forces
        # emails to be unique.
        #
        # If we want to allow client specified usernames, simply remove the
        # set username line.

        if (self.email is not None) and (self.email != ""):
            self.username = self.email

        super().save(*args, **kwargs)

    def ensure_staking_opted_in(self):
        """Auto-opt the user into staking if not already opted in."""
        if not self.is_staking_opted_in:
            self.is_staking_opted_in = True
            self.staking_opted_in_date = timezone.now()
            self.save(update_fields=["is_staking_opted_in", "staking_opted_in_date"])

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

    def get_locked_balance(self):
        """Returns total locked balance amount (promotional included)."""
        locked_queryset = self.get_balance_qs().filter(is_locked=True)
        return self.get_balance(queryset=locked_queryset, include_locked=True)

    def get_promotional_balance(self) -> Decimal:
        """Returns total promotional balance (locked, but earns yield)."""
        return self.get_locked_balance_by_lock_type().get(
            Balance.LockType.PROMOTIONAL, Decimal(0)
        )

    def get_funding_credits_balance(self) -> Decimal:
        """Returns the non-promotional locked balance.

        Promotional funds are also spendable on fundraises but are tracked
        separately because they earn yield and are consumed last.
        """
        return self.get_locked_balance_by_lock_type().get(
            Balance.LockType.FUNDING_CREDIT, Decimal(0)
        )

    def get_locked_balance_by_lock_type(self) -> dict[str, Decimal]:
        """Return effective, non-negative locked balances by category.

        Historical category debits can exceed credits even when the overall
        locked ledger is non-negative. Cap positive categories, in spend
        order, to the overall locked total so category debt cannot create
        spendable or yield-eligible funds in another category.
        """
        rows = (
            self.get_balance_qs()
            .filter(is_locked=True)
            .values("lock_type")
            .annotate(
                total=Sum(
                    Cast("amount", DecimalField(max_digits=255, decimal_places=128))
                )
            )
        )
        raw_balances = {row["lock_type"]: row["total"] or Decimal(0) for row in rows}

        valid_lock_types = set(Balance.LOCKED_SPEND_ORDER)
        unexpected_lock_types = set(raw_balances) - valid_lock_types
        if unexpected_lock_types:
            raise ValueError(
                "Unsupported locked balance types: "
                f"{sorted(str(value) for value in unexpected_lock_types)}"
            )

        remaining_total = max(sum(raw_balances.values(), Decimal(0)), Decimal(0))
        effective_balances = {}
        for lock_type in Balance.LOCKED_SPEND_ORDER:
            if lock_type not in raw_balances:
                continue
            available = max(raw_balances[lock_type], Decimal(0))
            effective_balances[lock_type] = min(available, remaining_total)
            remaining_total -= effective_balances[lock_type]

        return effective_balances

    def allocate_locked_spend(self, amount: Decimal) -> tuple[list[dict], Decimal]:
        """Split ``amount`` across locked categories in spend order.

        Consumes categories in ``Balance.LOCKED_SPEND_ORDER`` (yield-earning
        promotional funds last), capping each allocation at that category's
        effective balance so the debits written from it keep every category
        ledger — promotional yield netting in particular — correct.

        Returns ``(allocations, remaining)`` where ``allocations`` is a list
        of ``{"amount": Decimal, "is_locked": True, "lock_type": str}``
        and ``remaining`` is the portion locked funds could not cover.
        """
        remaining = Decimal(str(amount))
        if remaining <= 0:
            return [], Decimal(0)

        balances_by_type = self.get_locked_balance_by_lock_type()
        allocations = []
        for lock_type in Balance.LOCKED_SPEND_ORDER:
            if remaining <= 0:
                break
            available = balances_by_type.get(lock_type, Decimal(0))
            if available <= 0:
                continue
            use = min(available, remaining)
            allocations.append(
                {"amount": use, "is_locked": True, "lock_type": lock_type}
            )
            remaining -= use

        return allocations, remaining

    def get_unlocked_balance_lots_lifo(self) -> list[UnlockedBalanceLot]:
        """
        Reconstruct the user's remaining unlocked balance lots using LIFO.

        Negative balance rows consume the most recent positive rows first.
        """
        return self._balance_lots_lifo(self.get_balance_qs().filter(is_locked=False))

    def get_yield_eligible_balance_lots_lifo(self) -> list[UnlockedBalanceLot]:
        """
        Reconstruct the user's yield-earning balance lots using LIFO.

        Yield-eligible principal is the unlocked balance plus the effective
        promotional balance. Locked debt in another category caps promotional
        lots so it cannot generate yield on funds the user no longer owns.
        """
        promotional_lots = self._balance_lots_lifo(
            self.get_balance_qs().filter(
                is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
            )
        )
        promotional_lots = self._cap_balance_lots_lifo(
            promotional_lots, self.get_promotional_balance()
        )
        return self.get_unlocked_balance_lots_lifo() + promotional_lots

    @staticmethod
    def _cap_balance_lots_lifo(
        lots: list[UnlockedBalanceLot], maximum: Decimal
    ) -> list[UnlockedBalanceLot]:
        """Cap lots by applying any excess as a LIFO debit."""
        total = sum((lot.amount for lot in lots), Decimal(0))
        remaining_debit = max(total - max(maximum, Decimal(0)), Decimal(0))
        if remaining_debit == 0:
            return lots

        capped_lots = []
        for lot in lots:
            if remaining_debit >= lot.amount:
                remaining_debit -= lot.amount
                continue

            amount = lot.amount - remaining_debit
            remaining_debit = Decimal(0)
            capped_lots.append(
                UnlockedBalanceLot(amount=amount, created_date=lot.created_date)
            )

        return capped_lots

    def _balance_lots_lifo(self, queryset: models.QuerySet) -> list[UnlockedBalanceLot]:
        remaining_debits = Decimal(0)
        lots = []
        balance_rows = queryset.order_by("-created_date", "-id").only(
            "id", "amount", "created_date"
        )

        for balance in balance_rows.iterator():
            amount = Decimal(str(balance.amount))
            if amount < 0:
                remaining_debits += -amount
                continue

            if amount <= 0:
                continue

            if remaining_debits >= amount:
                remaining_debits -= amount
                continue

            remaining_amount = amount - remaining_debits
            remaining_debits = Decimal(0)

            if remaining_amount <= 0:
                continue

            lots.append(
                UnlockedBalanceLot(
                    amount=remaining_amount,
                    created_date=balance.created_date.date(),
                )
            )

        return lots

    def allocate_spend(self, amount: Decimal, allow_locked: bool = False) -> list[dict]:
        """
        Determine how to split ``amount`` across locked and unlocked balances.

        Locked funds are consumed first, per category in
        ``Balance.LOCKED_SPEND_ORDER`` (yield-earning promotional funds last).
        Debits written from these allocations must carry ``lock_type`` so each
        category — promotional yield netting in particular — stays correct
        and refunds can restore the exact category.

        Returns a list of dicts::

            [{"amount": Decimal, "is_locked": bool, "lock_type": str | None}]

        Raises ``ValueError`` if the user cannot cover ``amount``.
        """
        if amount <= 0:
            return []

        remaining = Decimal(str(amount))
        allocations = []

        if allow_locked:
            allocations, remaining = self.allocate_locked_spend(remaining)

        if remaining > 0:
            if self.get_available_balance() < remaining:
                raise ValueError("Insufficient balance")
            allocations.append(
                {"amount": remaining, "is_locked": False, "lock_type": None}
            )

        return allocations

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

    def is_moderator_or_editor(self):
        """Whether the user has elevated moderation reach.

        Site moderators and hub editors share the same privileged visibility
        across the app (e.g. seeing works still awaiting moderation), so the
        check lives in one place instead of being re-spelled at every call site.
        """
        return self.moderator or self.is_hub_editor()

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
    def amount_funded(self):
        from user.services.funding_activity_service import get_funder_total_amount

        return get_funder_total_amount(self.id)

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

        peer_review_count = (
            RhCommentModel.objects.filter(
                created_by=self,
                comment_type="REVIEW",
                is_removed=False,
                reviews__is_assessed=True,
                reviews__is_removed=False,
            )
            .distinct()
            .aggregate(count=Count("id"))["count"]
        )

        return peer_review_count
