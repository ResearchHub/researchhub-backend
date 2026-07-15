"""Unit tests for the profile-staleness check (pure function, no Django)."""

import unittest

from research_ai.services.proposal_draft.runner import (
    PROFILE_SCHEMA_VERSION,
    _needs_profile,
)


class NeedsProfileTests(unittest.TestCase):
    def test_missing_or_empty_needs_build(self):
        # Arrange / Act / Assert
        self.assertTrue(_needs_profile(None))
        self.assertTrue(_needs_profile({}))

    def test_unresolved_needs_build(self):
        # Arrange / Act / Assert: a dict without a resolution object is incomplete.
        self.assertTrue(_needs_profile({"schema_version": PROFILE_SCHEMA_VERSION}))

    def test_current_schema_is_reused(self):
        # Arrange
        profile = {"schema_version": PROFILE_SCHEMA_VERSION, "resolution": {}}
        # Act / Assert
        self.assertFalse(_needs_profile(profile))

    def test_older_schema_is_rebuilt(self):
        # Arrange: a pre-capabilities profile is stale even though it resolved.
        profile = {"schema_version": PROFILE_SCHEMA_VERSION - 1, "resolution": {}}
        # Act / Assert
        self.assertTrue(_needs_profile(profile))

    def test_unparseable_schema_is_rebuilt(self):
        # Arrange
        profile = {"schema_version": "bogus", "resolution": {}}
        # Act / Assert
        self.assertTrue(_needs_profile(profile))
