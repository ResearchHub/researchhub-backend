"""Unit tests for researcher_profile.builder entry points."""

from unittest.mock import patch

from django.test import TestCase

from research_ai.models import Expert
from research_ai.services.researcher_profile import builder


class StoreProfileTests(TestCase):
    @patch("research_ai.services.researcher_profile.builder.build_expert_profile")
    def test_build_and_store_persists_profile(self, mock_build):
        # Arrange
        profile = {"schema_version": 2, "works": []}
        mock_build.return_value = profile
        expert = Expert.objects.create(email="jane@example.com", first_name="Jane")
        # Act
        returned = builder.build_and_store_expert_profile(expert)
        # Assert
        expert.refresh_from_db()
        self.assertEqual(expert.profile, profile)
        self.assertEqual(returned, expert.profile)
        mock_build.assert_called_once_with(expert)
