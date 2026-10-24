"""Tests for ResearcherProfileService: lookup, build policy, and builds."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from research_ai.models import Expert, ResearcherProfile
from research_ai.services.agent.errors import BudgetExceededError
from research_ai.services.researcher_profile import (
    ResearcherProfileService,
    profile_service,
)
from research_ai.services.researcher_profile.agent import (
    NO_SUBMISSION_ERROR,
    SCHEMA_VERSION,
)
from research_ai.services.researcher_profile.profile_service import (
    FEATURE,
    MAX_ATTEMPTS,
    REFRESH_AFTER,
)
from research_ai.services.researcher_profile.seed import seed_for_profile
from research_ai.services.usage_budget import ModelNotAllowedError
from user.tests.helpers import create_user

Status = ResearcherProfile.Status
_RUNTIME = "research_ai.services.researcher_profile.profile_service._user_runtime"


def _built(openalex_author_id="A1", errors=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "built_at": "2026-10-24T00:00:00+00:00",
        "resolution": {
            "openalex_author_id": openalex_author_id,
            "display_name": "Jane Doe",
            "orcid": "0000-0001-2345-6789" if openalex_author_id else None,
            "confidence": 0.9 if openalex_author_id else 0.1,
            "reasoning": "",
        },
        "works": [{"title": "Paper", "source_url": "https://doi.org/10.1/a"}],
        "capabilities": [],
        "errors": errors or [],
    }


def _user(email="jane@example.edu"):
    return create_user(first_name="Jane", last_name="Doe", email=email)


def _current(profile: ResearcherProfile, **fields) -> ResearcherProfile:
    """Make ``profile`` a current, ready build of its present seed."""
    defaults = {
        "status": Status.READY,
        "schema_version": SCHEMA_VERSION,
        "built_at": timezone.now(),
        "data": _built(),
        "inputs_hash": seed_for_profile(profile).inputs_hash(),
    }
    defaults.update(fields)
    for name, value in defaults.items():
        setattr(profile, name, value)
    profile.save()
    return profile


class LookupTests(TestCase):
    def test_creates_a_user_profile_when_none_matches(self):
        # Arrange
        user = _user()
        # Act
        profile = ResearcherProfileService().get_or_create_for_user(user)
        # Assert
        self.assertEqual(profile.user, user)
        self.assertIsNone(profile.expert_id)
        self.assertEqual(profile.status, Status.PENDING)

    def test_user_adopts_their_matched_experts_unclaimed_profile(self):
        # Arrange
        user = _user()
        expert = Expert.objects.create(email=user.email)
        built = ResearcherProfile.objects.create(expert=expert, data=_built())
        # Act
        profile = ResearcherProfileService().get_or_create_for_user(user)
        # Assert
        self.assertEqual(profile.pk, built.pk)
        self.assertEqual(profile.user, user)
        self.assertEqual(ResearcherProfile.objects.count(), 1)

    def test_user_gets_own_row_when_experts_profile_has_another_owner(self):
        # Arrange
        user = _user()
        other = _user(email="other@example.edu")
        expert = Expert.objects.create(email=user.email)
        ResearcherProfile.objects.create(expert=expert, user=other)
        # Act
        profile = ResearcherProfileService().get_or_create_for_user(user)
        # Assert
        self.assertEqual(profile.user, user)
        self.assertIsNone(profile.expert_id)

    def test_new_user_profile_links_their_matched_expert(self):
        # Arrange
        user = _user()
        expert = Expert.objects.create(email=user.email)
        # Act
        profile = ResearcherProfileService().get_or_create_for_user(user)
        # Assert
        self.assertEqual(profile.expert, expert)

    def test_expert_adopts_their_registered_users_profile(self):
        # Arrange
        user = _user()
        built = ResearcherProfile.objects.create(user=user)
        expert = Expert.objects.create(email="jd@lab.edu", registered_user=user)
        # Act
        profile = ResearcherProfileService().get_or_create_for_expert(expert)
        # Assert
        self.assertEqual(profile.pk, built.pk)
        self.assertEqual(profile.expert, expert)

    def test_expert_reuses_their_existing_profile(self):
        # Arrange
        expert = Expert.objects.create(email="jd@lab.edu")
        existing = ResearcherProfile.objects.create(expert=expert)
        # Act
        profile = ResearcherProfileService().get_or_create_for_expert(expert)
        # Assert
        self.assertEqual(profile.pk, existing.pk)

    def test_creates_an_expert_profile_when_none_matches(self):
        # Arrange
        expert = Expert.objects.create(email="jd@lab.edu")
        # Act
        profile = ResearcherProfileService().get_or_create_for_expert(expert)
        # Assert
        self.assertEqual(profile.expert, expert)
        self.assertIsNone(profile.user_id)

    def test_concurrent_create_returns_the_row_that_won(self):
        # Arrange: another trigger created the user's row first.
        user = _user()
        winner = ResearcherProfile.objects.create(user=user)
        # Act
        profile = ResearcherProfileService()._create(user=user)
        # Assert
        self.assertEqual(profile.pk, winner.pk)

    def test_concurrent_create_with_a_taken_expert_gives_the_user_a_row(self):
        # Arrange: the expert was claimed by another row in the meantime.
        user = _user()
        expert = Expert.objects.create(email="jd@lab.edu")
        ResearcherProfile.objects.create(expert=expert)
        # Act
        profile = ResearcherProfileService()._create(user=user, expert=expert)
        # Assert
        self.assertEqual(profile.user, user)
        self.assertIsNone(profile.expert_id)

    def test_adopt_refuses_a_user_who_already_has_a_profile(self):
        # Arrange
        user = _user()
        ResearcherProfile.objects.create(user=user)
        orphan = ResearcherProfile.objects.create(
            expert=Expert.objects.create(email="jd@lab.edu")
        )
        # Act
        adopted = ResearcherProfileService()._adopt(orphan, user=user)
        # Assert
        self.assertFalse(adopted)
        orphan.refresh_from_db()
        self.assertIsNone(orphan.user_id)

    def test_profile_for_user_does_not_write(self):
        # Arrange
        user = _user()
        # Act
        profile = ResearcherProfileService().profile_for_user(user)
        # Assert
        self.assertIsNone(profile)
        self.assertFalse(ResearcherProfile.objects.exists())


class NeedsBuildTests(TestCase):
    def setUp(self):
        self.service = ResearcherProfileService()
        self.profile = ResearcherProfile.objects.create(user=_user())

    def test_pending_profile_needs_a_build(self):
        # Act & Assert
        self.assertTrue(self.service.needs_build(self.profile))

    def test_current_profile_does_not(self):
        # Arrange
        _current(self.profile)
        # Act & Assert
        self.assertFalse(self.service.needs_build(self.profile))

    def test_unresolved_current_profile_does_not(self):
        # Arrange
        _current(self.profile, status=Status.UNRESOLVED, data=_built(None))
        # Act & Assert
        self.assertFalse(self.service.needs_build(self.profile))

    def test_older_schema_needs_a_rebuild(self):
        # Arrange
        _current(self.profile, schema_version=SCHEMA_VERSION - 1)
        # Act & Assert
        self.assertTrue(self.service.needs_build(self.profile))

    def test_profile_past_the_refresh_window_needs_a_rebuild(self):
        # Arrange
        old = timezone.now() - REFRESH_AFTER - timedelta(days=1)
        _current(self.profile, built_at=old)
        # Act & Assert
        self.assertTrue(self.service.needs_build(self.profile))

    def test_changed_seed_needs_a_rebuild(self):
        # Arrange
        _current(self.profile)
        author = self.profile.user.author_profile
        author.orcid_id = "https://orcid.org/0000-0002-0000-0001"
        author.save()
        self.profile.user.refresh_from_db()
        # Act & Assert
        self.assertTrue(self.service.needs_build(self.profile))

    def test_blank_hash_of_a_copied_profile_is_not_a_change(self):
        # Arrange
        _current(self.profile, inputs_hash="")
        # Act & Assert
        self.assertFalse(self.service.needs_build(self.profile))

    def test_failed_profile_waits_for_its_backoff(self):
        # Arrange
        _current(
            self.profile,
            status=Status.FAILED,
            attempts=1,
            next_attempt_at=timezone.now() + timedelta(minutes=5),
        )
        # Act & Assert
        self.assertFalse(self.service.needs_build(self.profile))

    def test_failed_profile_is_retried_once_its_backoff_passes(self):
        # Arrange
        _current(
            self.profile,
            status=Status.FAILED,
            attempts=1,
            next_attempt_at=timezone.now() - timedelta(minutes=5),
        )
        # Act & Assert
        self.assertTrue(self.service.needs_build(self.profile))

    def test_failed_profile_stops_after_max_attempts(self):
        # Arrange
        _current(self.profile, status=Status.FAILED, attempts=MAX_ATTEMPTS)
        # Act & Assert
        self.assertFalse(self.service.needs_build(self.profile))

    def test_live_lease_blocks_a_second_build(self):
        # Arrange
        self.profile.status = Status.BUILDING
        self.profile.lease_expires_at = timezone.now() + timedelta(minutes=5)
        self.profile.save()
        # Act & Assert
        self.assertFalse(self.service.needs_build(self.profile))

    def test_lapsed_lease_is_picked_up_again(self):
        # Arrange
        self.profile.status = Status.BUILDING
        self.profile.lease_expires_at = timezone.now() - timedelta(minutes=5)
        self.profile.save()
        # Act & Assert
        self.assertTrue(self.service.needs_build(self.profile))

    def test_nameless_user_without_identifiers_is_not_built(self):
        # Arrange
        user = create_user(first_name="", last_name="", email="anon@example.edu")
        author = user.author_profile
        author.first_name = author.last_name = ""
        author.save()
        profile = ResearcherProfile.objects.create(user=user)
        # Act & Assert
        self.assertFalse(self.service.needs_build(profile))


class EnsureTests(TestCase):
    def setUp(self):
        self.profile = ResearcherProfile.objects.create(user=_user())

    def test_successful_build_stores_data_and_promoted_columns(self):
        # Arrange
        build = Mock(return_value=_built())
        service = ResearcherProfileService(build=build)
        # Act
        service.ensure(self.profile)
        # Assert
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, Status.READY)
        self.assertEqual(self.profile.openalex_author_id, "A1")
        self.assertEqual(self.profile.orcid, "0000-0001-2345-6789")
        self.assertEqual(self.profile.confidence, 0.9)
        self.assertEqual(self.profile.schema_version, SCHEMA_VERSION)
        self.assertEqual(
            self.profile.inputs_hash, seed_for_profile(self.profile).inputs_hash()
        )
        self.assertIsNotNone(self.profile.built_at)
        self.assertIsNone(self.profile.lease_expires_at)
        self.assertFalse(service.needs_build(self.profile))

    def test_subject_adopted_during_the_build_survives_the_save(self):
        # Arrange: an expert-only profile whose user is linked mid-build.
        expert = Expert.objects.create(email="jd@lab.edu", first_name="Jane")
        profile = ResearcherProfile.objects.create(expert=expert)
        user = _user("late@example.edu")

        def build(seed, **kwargs):
            ResearcherProfileService()._adopt(profile, user=user)
            return _built()

        # Act
        ResearcherProfileService(build=build).ensure(profile)
        # Assert
        profile.refresh_from_db()
        self.assertEqual(profile.user, user)
        self.assertEqual(profile.status, Status.READY)

    def test_build_runs_on_the_profiles_seed(self):
        # Arrange
        build = Mock(return_value=_built())
        # Act
        ResearcherProfileService(build=build).ensure(self.profile)
        # Assert
        seed = build.call_args.args[0]
        self.assertEqual(seed.name, "Jane Doe")

    def test_unresolved_build_is_stored_as_unresolved(self):
        # Arrange
        service = ResearcherProfileService(build=Mock(return_value=_built(None)))
        # Act
        service.ensure(self.profile)
        # Assert
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, Status.UNRESOLVED)
        self.assertEqual(self.profile.openalex_author_id, "")

    def test_failed_rebuild_keeps_the_previous_data_and_backs_off(self):
        # Arrange
        _current(self.profile, schema_version=SCHEMA_VERSION - 1)
        previous = self.profile.data
        failed = _built(None, errors=[NO_SUBMISSION_ERROR])
        service = ResearcherProfileService(build=Mock(return_value=failed))
        # Act
        service.ensure(self.profile)
        # Assert
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, Status.FAILED)
        self.assertEqual(self.profile.data, previous)
        self.assertEqual(self.profile.attempts, 1)
        self.assertIn(NO_SUBMISSION_ERROR, self.profile.last_error)
        self.assertGreater(self.profile.next_attempt_at, timezone.now())

    def test_build_exception_is_recorded_as_a_failure(self):
        # Arrange
        service = ResearcherProfileService(build=Mock(side_effect=RuntimeError("x")))
        # Act
        service.ensure(self.profile)
        # Assert
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, Status.FAILED)
        self.assertIn("build: x", self.profile.last_error)

    def test_budget_exhaustion_releases_the_claim_and_propagates(self):
        # Arrange
        service = ResearcherProfileService(
            build=Mock(side_effect=BudgetExceededError("over"))
        )
        # Act & Assert
        with self.assertRaises(BudgetExceededError):
            service.ensure(self.profile)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, Status.PENDING)
        self.assertIsNone(self.profile.lease_expires_at)
        self.assertEqual(self.profile.attempts, 0)

    def test_does_not_build_while_another_build_holds_the_lease(self):
        # Arrange
        build = Mock(return_value=_built())
        ResearcherProfile.objects.filter(pk=self.profile.pk).update(
            status=Status.BUILDING,
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )
        # Act: the in-memory row is stale; the claim re-reads under lock.
        ResearcherProfileService(build=build).ensure(self.profile)
        # Assert
        build.assert_not_called()

    def test_current_profile_is_not_rebuilt(self):
        # Arrange
        _current(self.profile)
        build = Mock()
        # Act
        ResearcherProfileService(build=build).ensure(self.profile)
        # Assert
        build.assert_not_called()


class EnsureForUserTests(TestCase):
    def test_builds_on_the_users_tier_runtime(self):
        # Arrange
        user = _user()
        provider, recorder = object(), object()
        build = Mock(return_value=_built())
        # Act
        with patch(_RUNTIME, return_value=(provider, recorder)):
            profile = ResearcherProfileService(build=build).ensure_for_user(user)
        # Assert
        self.assertEqual(profile.status, Status.READY)
        _args, kwargs = build.call_args
        self.assertIs(kwargs["provider"], provider)
        self.assertIs(kwargs["recorder"], recorder)

    def test_current_profile_is_not_rebuilt_in_the_background(self):
        # Arrange
        user = _user()
        _current(ResearcherProfile.objects.create(user=user))
        # Act
        with patch(_RUNTIME) as runtime:
            ResearcherProfileService(build=Mock()).ensure_for_user(user)
        # Assert
        runtime.assert_not_called()

    def test_blocked_user_is_skipped(self):
        # Arrange
        user = _user()
        build = Mock()
        # Act
        with patch(_RUNTIME, side_effect=ModelNotAllowedError("blocked")):
            profile = ResearcherProfileService(build=build).ensure_for_user(user)
        # Assert
        build.assert_not_called()
        self.assertEqual(profile.status, Status.PENDING)
        self.assertGreater(profile.next_attempt_at, timezone.now())

    def test_unbuildable_seed_is_deferred(self):
        # Arrange
        user = create_user(first_name="", last_name="", email="anon@example.edu")
        author = user.author_profile
        author.first_name = author.last_name = ""
        author.save()
        build = Mock()
        # Act
        profile = ResearcherProfileService(build=build).ensure_for_user(user)
        # Assert
        build.assert_not_called()
        self.assertGreater(profile.next_attempt_at, timezone.now())

    def test_exhausted_budget_defers_the_build(self):
        # Arrange
        user = _user()
        build = Mock(side_effect=BudgetExceededError("over"))
        # Act
        with patch(_RUNTIME, return_value=(object(), object())):
            profile = ResearcherProfileService(build=build).ensure_for_user(user)
        # Assert
        self.assertEqual(profile.status, Status.PENDING)
        self.assertGreater(profile.next_attempt_at, timezone.now())


class DueForSweepTests(TestCase):
    def test_lists_users_of_due_profiles_only(self):
        # Arrange
        pending = ResearcherProfile.objects.create(user=_user("a@example.edu"))
        stale = _current(
            ResearcherProfile.objects.create(user=_user("b@example.edu")),
            built_at=timezone.now() - REFRESH_AFTER - timedelta(days=1),
        )
        _current(ResearcherProfile.objects.create(user=_user("c@example.edu")))
        ResearcherProfile.objects.create(
            user=_user("d@example.edu"), status=Status.FAILED, attempts=MAX_ATTEMPTS
        )
        ResearcherProfile.objects.create(expert=Expert.objects.create(email="e@x.edu"))
        # Act
        due = ResearcherProfileService().due_for_sweep(limit=10)
        # Assert
        self.assertCountEqual(due, [pending.user_id, stale.user_id])

    def test_skips_rows_waiting_out_a_deferral(self):
        # Arrange: a deferred pending row ahead of a fresh one in sweep order.
        deferred = ResearcherProfile.objects.create(
            user=_user("a@example.edu"),
            next_attempt_at=timezone.now() + timedelta(hours=12),
        )
        fresh = ResearcherProfile.objects.create(user=_user("b@example.edu"))
        # Act
        due = ResearcherProfileService().due_for_sweep(limit=1)
        # Assert
        self.assertEqual(due, [fresh.user_id])
        self.assertNotIn(deferred.user_id, due)

    def test_respects_the_limit(self):
        # Arrange
        for index in range(3):
            ResearcherProfile.objects.create(user=_user(f"u{index}@example.edu"))
        # Act & Assert
        self.assertEqual(len(ResearcherProfileService().due_for_sweep(limit=2)), 2)


class UserRuntimeTests(TestCase):
    def test_builds_on_the_tier_default_model_charged_to_the_user(self):
        # Arrange
        user = _user()
        policy = Mock()
        policy.name = "default"
        provider = Mock(model_id="model-x")
        with (
            patch.object(profile_service, "resolve_ai_tier", return_value=policy),
            patch.object(
                profile_service, "resolve_default_model", return_value="bedrock:m"
            ),
            patch.object(
                profile_service,
                "effective_generation_options",
                return_value=("low", None),
            ),
            patch.object(
                profile_service, "resolve_provider", return_value=provider
            ) as resolve_provider,
        ):
            # Act
            built_provider, recorder = profile_service._user_runtime(user)
        # Assert
        self.assertIs(built_provider, provider)
        resolve_provider.assert_called_once_with("bedrock:m", effort="low")
        self.assertEqual(recorder.user, user)
        self.assertEqual(recorder.feature, FEATURE)
        self.assertEqual(recorder.provider, "bedrock")
        self.assertEqual(recorder.model_id, "model-x")

    def test_blocked_tier_raises(self):
        # Arrange
        policy = Mock()
        policy.name = "blocked"
        # Act & Assert
        with (
            patch.object(profile_service, "resolve_ai_tier", return_value=policy),
            self.assertRaises(ModelNotAllowedError),
        ):
            profile_service._user_runtime(_user())


class ProfileModelTests(TestCase):
    def test_str_names_the_row_and_status(self):
        # Arrange
        profile = ResearcherProfile.objects.create(user=_user())
        # Act & Assert
        self.assertEqual(str(profile), f"ResearcherProfile {profile.id} (PENDING)")
