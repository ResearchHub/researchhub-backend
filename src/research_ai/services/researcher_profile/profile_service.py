"""Owns ``ResearcherProfile`` rows: finding them, deciding when to build, building.

A profile is built at most once at a time: ``ensure`` claims the row under a
lock and holds a lease while the agent runs, so concurrent triggers (a chat
opening, a proposal draft, the nightly sweep) never pay for the same build
twice. A build that lapses its lease is picked up again by the next trigger.

When a profile is (re)built:

- it has never been built, or its schema is older than the agent's;
- the seed changed (the researcher edited their ORCID, OpenAlex ids, ...);
- it failed, with exponential backoff up to ``MAX_ATTEMPTS``;
- it is older than ``REFRESH_AFTER``, to pick up new papers.

A rebuild keeps the previous ``data`` until the new one lands, and a failed
rebuild never overwrites good data.
"""

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from research_ai.models import ResearcherProfile
from research_ai.services.agent import resolve_provider
from research_ai.services.agent.errors import BudgetExceededError
from research_ai.services.agent.providers.registry import split_model_ref
from research_ai.services.researcher_profile.agent import (
    NO_SUBMISSION_ERROR,
    SCHEMA_VERSION,
    run_profile_agent,
)
from research_ai.services.researcher_profile.seed import (
    ProfileSeed,
    seed_for_profile,
)
from research_ai.services.researcher_profile.user_expert import expert_for_user
from research_ai.services.usage_budget import (
    AgentLoopBudgetRecorder,
    ModelNotAllowedError,
    effective_generation_options,
    resolve_ai_tier,
    resolve_default_model,
)

logger = logging.getLogger(__name__)

FEATURE = "researcher_profile"
LEASE = timedelta(minutes=30)
MAX_ATTEMPTS = 5
REFRESH_AFTER = timedelta(days=180)
RETRY_BASE = timedelta(hours=1)  # doubled per consecutive failure
_MAX_ERROR_CHARS = 2000
DEFER = timedelta(days=1)  # sweep holds off a row it could not build
_BUILD_FIELDS = [
    "data",
    "status",
    "schema_version",
    "openalex_author_id",
    "orcid",
    "confidence",
    "inputs_hash",
    "built_at",
    "attempts",
    "last_error",
    "next_attempt_at",
    "lease_expires_at",
    "updated_date",
]

Status = ResearcherProfile.Status


class ResearcherProfileService:
    """Find, schedule and build researcher profiles.

    ``build`` (the agent run) and ``now`` are injectable for tests.
    """

    def __init__(self, *, build=run_profile_agent, now=timezone.now):
        self._build = build
        self._now = now

    # -- lookup -----------------------------------------------------------

    def profile_for_user(self, user) -> ResearcherProfile | None:
        """The user's profile, or their matched expert's, without writing."""
        profile = ResearcherProfile.objects.filter(user=user).first()
        if profile is not None:
            return profile
        expert = expert_for_user(user)
        if expert is None:
            return None
        return ResearcherProfile.objects.filter(expert=expert).first()

    def get_or_create_for_user(self, user) -> ResearcherProfile:
        """The user's profile, adopting their matched expert's row when unclaimed."""
        profile = ResearcherProfile.objects.filter(user=user).first()
        if profile is not None:
            return profile
        expert = expert_for_user(user)
        if expert is None:
            return self._create(user=user)
        expert_profile = ResearcherProfile.objects.filter(expert=expert).first()
        if expert_profile is None:
            return self._create(user=user, expert=expert)
        if self._adopt(expert_profile, user=user):
            return ResearcherProfile.objects.get(pk=expert_profile.pk)
        # The expert's profile already belongs to another account.
        return self._create(user=user)

    def get_or_create_for_expert(self, expert) -> ResearcherProfile:
        """The expert's profile, adopting their registered user's row when unclaimed."""
        profile = ResearcherProfile.objects.filter(expert=expert).first()
        if profile is not None:
            return profile
        if expert.registered_user_id is not None:
            user_profile = ResearcherProfile.objects.filter(
                user_id=expert.registered_user_id
            ).first()
            if user_profile is not None and self._adopt(user_profile, expert=expert):
                return ResearcherProfile.objects.get(pk=user_profile.pk)
        return self._create(expert=expert)

    # -- build policy -----------------------------------------------------

    def needs_build(
        self, profile: ResearcherProfile, seed: ProfileSeed | None = None
    ) -> bool:
        now = self._now()
        if profile.status == Status.BUILDING and _lease_live(profile, now):
            return False
        seed = seed_for_profile(profile) if seed is None else seed
        if not seed.is_buildable:
            return False
        # A blank hash means no seed was recorded; never-built rows are
        # PENDING and caught below.
        if profile.inputs_hash and profile.inputs_hash != seed.inputs_hash():
            return True
        if profile.status == Status.FAILED:
            return profile.attempts < MAX_ATTEMPTS and (
                profile.next_attempt_at is None or profile.next_attempt_at <= now
            )
        if profile.status in (Status.PENDING, Status.BUILDING) or not profile.has_data:
            return True
        if profile.schema_version < SCHEMA_VERSION:
            return True
        return profile.built_at is None or profile.built_at < now - REFRESH_AFTER

    def due_for_sweep(self, *, limit: int) -> list[int]:
        """User ids whose profiles the nightly sweep should hand to ``ensure``.

        Seed changes are not detected here (that needs each user's author
        row); the chat triggers catch those when the user next opens a chat.
        Rows waiting out a retry backoff or a deferral are skipped until then.
        """
        now = self._now()
        due = (
            Q(status=Status.PENDING)
            | Q(status=Status.BUILDING, lease_expires_at__lt=now)
            | Q(status=Status.BUILDING, lease_expires_at__isnull=True)
            | Q(status=Status.FAILED, attempts__lt=MAX_ATTEMPTS)
            | Q(
                Q(schema_version__lt=SCHEMA_VERSION)
                | Q(built_at__isnull=True)
                | Q(built_at__lt=now - REFRESH_AFTER),
                status__in=(Status.READY, Status.UNRESOLVED),
            )
        )
        not_waiting = Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
        return list(
            ResearcherProfile.objects.filter(due, not_waiting, user__isnull=False)
            .order_by("updated_date")
            .values_list("user_id", flat=True)[:limit]
        )

    # -- build ------------------------------------------------------------

    def ensure(
        self,
        profile: ResearcherProfile,
        *,
        provider=None,
        oa_client=None,
        recorder=None,
    ) -> ResearcherProfile:
        """Build ``profile`` in place when it needs it and no one else is.

        Budget exhaustion propagates (the claim is released first); any other
        failure is recorded on the row for a later retry.
        """
        seed = seed_for_profile(profile)
        if not self.needs_build(profile, seed):
            return profile
        previous_status = self._claim(profile, seed)
        if previous_status is None:
            return profile
        try:
            data = self._build(
                seed, provider=provider, oa_client=oa_client, recorder=recorder
            )
        except BudgetExceededError:
            self._release(profile, previous_status)
            raise
        except Exception as exc:  # noqa: BLE001 - recorded for retry
            logger.exception("researcher profile %s build failed", profile.pk)
            self._record_failure(profile, seed, [f"build: {exc}"])
            return profile
        errors = list(data.get("errors") or [])
        if NO_SUBMISSION_ERROR in errors:
            self._record_failure(profile, seed, errors)
        else:
            self._record_success(profile, seed, data)
        return profile

    def ensure_for_user(self, user) -> ResearcherProfile:
        """Background build for ``user``, charged to their Research AI budget.

        A row that cannot be built now (nothing to search on, blocked tier,
        exhausted budget) is deferred, so the sweep moves on to other rows
        instead of selecting it again every night.
        """
        profile = self.get_or_create_for_user(user)
        seed = seed_for_profile(profile)
        if not seed.is_buildable:
            self._defer(profile)
            return profile
        if not self.needs_build(profile, seed):
            return profile
        try:
            provider, recorder = _user_runtime(user)
        except ModelNotAllowedError as exc:
            logger.info("researcher profile for user %s skipped: %s", user.pk, exc)
            self._defer(profile)
            return profile
        try:
            return self.ensure(profile, provider=provider, recorder=recorder)
        except BudgetExceededError as exc:
            logger.info("researcher profile for user %s deferred: %s", user.pk, exc)
            self._defer(profile)
            return profile

    # -- row writes -------------------------------------------------------

    def _create(self, *, user=None, expert=None) -> ResearcherProfile:
        try:
            with transaction.atomic():
                return ResearcherProfile.objects.create(user=user, expert=expert)
        except IntegrityError:
            # A concurrent trigger created the row first.
            lookup = {"user": user} if user is not None else {"expert": expert}
            existing = ResearcherProfile.objects.filter(**lookup).first()
            if existing is not None:
                return existing
            if user is not None and expert is not None:
                # Only the expert was taken; give the user their own row.
                return self._create(user=user)
            raise

    def _adopt(self, profile: ResearcherProfile, *, user=None, expert=None) -> bool:
        """Attach the missing subject to ``profile`` if it is still unclaimed."""
        field = "user" if user is not None else "expert"
        try:
            with transaction.atomic():
                return bool(
                    ResearcherProfile.objects.filter(
                        pk=profile.pk, **{f"{field}__isnull": True}
                    ).update(**{field: user or expert, "updated_date": self._now()})
                )
        except IntegrityError:
            return False

    def _claim(self, profile: ResearcherProfile, seed: ProfileSeed) -> str | None:
        """Mark ``profile`` BUILDING; the status it had, or ``None`` if taken."""
        with transaction.atomic():
            locked = ResearcherProfile.objects.select_for_update().get(pk=profile.pk)
            if not self.needs_build(locked, seed):
                profile.refresh_from_db()
                return None
            previous_status = locked.status
            locked.status = Status.BUILDING
            locked.lease_expires_at = self._now() + LEASE
            locked.save(update_fields=["status", "lease_expires_at", "updated_date"])
        profile.refresh_from_db()
        return previous_status

    def _defer(self, profile: ResearcherProfile) -> None:
        profile.next_attempt_at = self._now() + DEFER
        profile.save(update_fields=["next_attempt_at", "updated_date"])

    def _release(self, profile: ResearcherProfile, previous_status: str) -> None:
        profile.status = previous_status
        profile.lease_expires_at = None
        profile.save(update_fields=["status", "lease_expires_at", "updated_date"])

    def _record_success(
        self, profile: ResearcherProfile, seed: ProfileSeed, data: dict
    ) -> None:
        resolution = data.get("resolution") or {}
        profile.data = data
        profile.status = (
            Status.READY if resolution.get("openalex_author_id") else Status.UNRESOLVED
        )
        profile.schema_version = int(data.get("schema_version") or 0)
        profile.openalex_author_id = resolution.get("openalex_author_id") or ""
        profile.orcid = resolution.get("orcid") or ""
        profile.confidence = resolution.get("confidence")
        profile.inputs_hash = seed.inputs_hash()
        profile.built_at = self._now()
        profile.attempts = 0
        profile.last_error = "; ".join(data.get("errors") or [])[:_MAX_ERROR_CHARS]
        profile.next_attempt_at = None
        profile.lease_expires_at = None
        # Never the subject links: a user or expert may have been adopted onto
        # this row while the build ran, and the in-memory copy predates that.
        profile.save(update_fields=_BUILD_FIELDS)

    def _record_failure(
        self, profile: ResearcherProfile, seed: ProfileSeed, errors: list[str]
    ) -> None:
        now = self._now()
        if profile.inputs_hash != seed.inputs_hash():
            # New inputs start a fresh run of retries.
            profile.attempts = 0
        profile.attempts += 1
        profile.status = Status.FAILED
        profile.inputs_hash = seed.inputs_hash()
        profile.last_error = "; ".join(errors)[:_MAX_ERROR_CHARS]
        profile.next_attempt_at = now + RETRY_BASE * 2 ** (profile.attempts - 1)
        profile.lease_expires_at = None
        profile.save(
            update_fields=[
                "attempts",
                "status",
                "inputs_hash",
                "last_error",
                "next_attempt_at",
                "lease_expires_at",
                "updated_date",
            ]
        )


def schedule_profile_build(user) -> None:
    """Queue ``ensure_for_user`` once the current transaction commits.

    Cheap to over-call: the task is a no-op when the profile is current or
    another build holds the lease.
    """
    if user is None or getattr(user, "pk", None) is None:
        return
    user_id = user.pk

    def _enqueue():
        # Imported here, not at module top: ``tasks`` imports this service, so
        # a top-level import would be a cycle.
        from research_ai.tasks import ensure_researcher_profile_task

        try:
            ensure_researcher_profile_task.delay(user_id)
        except Exception:  # noqa: BLE001 - a missed trigger is retried later
            logger.exception("could not queue researcher profile for user %s", user_id)

    transaction.on_commit(_enqueue)


def _lease_live(profile: ResearcherProfile, now) -> bool:
    return profile.lease_expires_at is not None and profile.lease_expires_at > now


def _user_runtime(user):
    """The provider and budget recorder a background build runs on for ``user``.

    Mirrors the user's tier: its default model and effort/thinking defaults,
    and spend charged to their daily Research AI budget.
    """
    policy = resolve_ai_tier(user)
    if policy.name == "blocked":
        raise ModelNotAllowedError("Research AI access is blocked")
    model_ref = resolve_default_model(policy)
    effort, thinking = effective_generation_options(policy, effort=None, thinking=None)
    provider = resolve_provider(
        model_ref,
        **{
            key: value
            for key, value in {"effort": effort, "thinking": thinking}.items()
            if value is not None
        },
    )
    provider_name, model_id = split_model_ref(model_ref)
    recorder = AgentLoopBudgetRecorder(
        user=user,
        feature=FEATURE,
        provider=provider_name,
        model_id=getattr(provider, "model_id", None) or model_id or "",
    )
    return provider, recorder
