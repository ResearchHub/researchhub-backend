"""Tests for the notebook chat researcher-profile read tool."""

from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from research_ai.models import Expert
from research_ai.services.notebook_chat.researcher_profile_tools import (
    GET_RESEARCHER_PROFILE,
    ResearcherProfileToolset,
)
from research_ai.services.notebook_chat.toolset import compose_notebook_toolset


def _make_user(email="jane@researchhub_test.com"):
    return get_user_model().objects.create_user(
        username=email, password="password", email=email
    )


def _handler(toolset: ResearcherProfileToolset):
    (tool,) = toolset.build_tools()
    return tool.handler


class GetResearcherProfileToolTests(TestCase):
    def test_reports_no_profile_without_an_expert_row(self):
        # Arrange
        toolset = ResearcherProfileToolset(user=_make_user())
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "no_profile")
        self.assertIn("never invent a track record", result["guidance"])

    def test_reports_no_profile_for_an_empty_profile(self):
        # Arrange
        user = _make_user()
        Expert.objects.create(email=user.email, registered_user=user, profile={})
        toolset = ResearcherProfileToolset(user=user)
        # Act & Assert
        self.assertEqual(_handler(toolset)({})["status"], "no_profile")

    def test_returns_profile_without_internal_errors_key(self):
        # Arrange
        user = _make_user()
        Expert.objects.create(
            email=user.email,
            registered_user=user,
            profile={
                "schema_version": 2,
                "built_at": "2026-08-26T00:00:00Z",
                "resolution": {"openalex_author_id": "A1"},
                "works": [{"title": "Paper"}],
                "capabilities": [{"name": "scRNA-seq"}],
                "errors": ["internal"],
            },
        )
        toolset = ResearcherProfileToolset(user=user)
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["profile"]["works"], [{"title": "Paper"}])
        self.assertEqual(result["profile"]["capabilities"], [{"name": "scRNA-seq"}])
        self.assertNotIn("errors", result["profile"])

    def test_email_matched_row_is_readable_without_registration_link(self):
        # Arrange
        user = _make_user()
        Expert.objects.create(
            email=user.email,
            profile={"resolution": {"openalex_author_id": "A1"}, "works": []},
        )
        toolset = ResearcherProfileToolset(user=user)
        # Act
        result = _handler(toolset)({})
        # Assert
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["profile"]["works"], [])


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
            web_search_toolset=empty,
        )
        # Assert
        self.assertIn(GET_RESEARCHER_PROFILE, toolset.names)
