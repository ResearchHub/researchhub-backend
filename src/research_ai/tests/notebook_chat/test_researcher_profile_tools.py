"""Tests for the notebook chat researcher-profile read tool."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from research_ai.models import Expert, ResearcherProfile
from research_ai.services.notebook_chat.researcher_profile_tools import (
    GET_RESEARCHER_PROFILE,
    ResearcherProfileToolset,
)
from research_ai.services.notebook_chat.toolset import compose_notebook_toolset
from research_ai.services.researcher_profile.agent import SCHEMA_VERSION

_SCHEDULE = (
    "research_ai.services.notebook_chat.researcher_profile_tools.schedule_profile_build"
)
_DATA = {
    "schema_version": SCHEMA_VERSION,
    "built_at": "2026-08-26T00:00:00Z",
    "resolution": {"openalex_author_id": "A1"},
    "works": [{"title": "Paper"}],
    "capabilities": [{"name": "scRNA-seq"}],
    "errors": ["internal"],
}


def _make_user(email="jane@researchhub_test.com"):
    return get_user_model().objects.create_user(
        username=email,
        password="password",
        email=email,
        first_name="Jane",
        last_name="Doe",
    )


def _handler(toolset: ResearcherProfileToolset):
    (tool,) = toolset.build_tools()
    return tool.handler


def _ready_profile(**fields):
    return ResearcherProfile.objects.create(
        status=ResearcherProfile.Status.READY,
        schema_version=SCHEMA_VERSION,
        built_at=timezone.now(),
        data=_DATA,
        **fields,
    )


@patch(_SCHEDULE)
class GetResearcherProfileToolTests(TestCase):
    def test_queues_a_build_and_reports_building_without_a_profile(self, schedule):
        # Arrange
        user = _make_user()
        toolset = ResearcherProfileToolset(user=user)
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "building")
        self.assertIn("never invent a track record", result["guidance"])
        schedule.assert_called_once_with(user)

    def test_returns_current_profile_without_errors_key_or_rebuild(self, schedule):
        # Arrange
        user = _make_user()
        _ready_profile(user=user)
        toolset = ResearcherProfileToolset(user=user)
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["profile"]["works"], [{"title": "Paper"}])
        self.assertEqual(result["profile"]["capabilities"], [{"name": "scRNA-seq"}])
        self.assertNotIn("errors", result["profile"])
        schedule.assert_not_called()

    def test_stale_profile_is_served_while_a_refresh_is_queued(self, schedule):
        # Arrange
        user = _make_user()
        profile = _ready_profile(user=user)
        ResearcherProfile.objects.filter(pk=profile.pk).update(
            built_at=timezone.now() - timedelta(days=365)
        )
        toolset = ResearcherProfileToolset(user=user)
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "ready")
        schedule.assert_called_once_with(user)

    def test_reads_the_profile_of_an_email_matched_expert(self, schedule):
        # Arrange
        user = _make_user()
        expert = Expert.objects.create(email=user.email)
        _ready_profile(expert=expert)
        toolset = ResearcherProfileToolset(user=user)
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "ready")

    def test_reports_building_while_a_first_build_holds_the_lease(self, schedule):
        # Arrange
        user = _make_user()
        ResearcherProfile.objects.create(
            user=user,
            status=ResearcherProfile.Status.BUILDING,
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )
        toolset = ResearcherProfileToolset(user=user)
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "building")
        schedule.assert_not_called()

    def test_failed_rebuild_serves_kept_data_as_stale(self, schedule):
        # Arrange
        user = _make_user()
        _ready_profile(user=user)
        ResearcherProfile.objects.filter(user=user).update(
            status=ResearcherProfile.Status.FAILED, attempts=99
        )
        toolset = ResearcherProfileToolset(user=user)
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["profile"]["works"], [{"title": "Paper"}])
        self.assertIn("different person", result["guidance"])

    def test_reports_no_profile_when_retries_are_exhausted(self, schedule):
        # Arrange
        user = _make_user()
        ResearcherProfile.objects.create(
            user=user, status=ResearcherProfile.Status.FAILED, attempts=99
        )
        toolset = ResearcherProfileToolset(user=user)
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "no_profile")
        schedule.assert_not_called()


class ComposeToolsetTests(TestCase):
    def test_researcher_profile_tool_is_registered(self):
        # Arrange
        empty = Mock(build_tools=Mock(return_value=[]))
        # Act
        toolset = compose_notebook_toolset(
            note_toolset=empty,
            user_profile_toolset=empty,
            researcher_profile_toolset=ResearcherProfileToolset(user=_make_user()),
            grant_toolset=empty,
            openalex_toolset=Mock(build_tools=Mock(return_value=[])),
            citation_toolset=empty,
            web_search_toolset=empty,
        )
        # Assert
        self.assertIn(GET_RESEARCHER_PROFILE, toolset.names)
