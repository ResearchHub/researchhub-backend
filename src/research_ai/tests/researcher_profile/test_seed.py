"""Tests for the researcher-profile agent seed."""

import unittest

from django.test import TestCase

from research_ai.services.researcher_profile.seed import (
    ProfileSeed,
    seed_from_expert,
    seed_from_user,
)
from research_ai.tests.researcher_profile.helpers import make_expert
from user.tests.helpers import create_user


class SeedFromUserTests(TestCase):
    def test_uses_the_authors_verified_identifiers(self):
        # Arrange
        user = create_user(first_name="Jane", last_name="Doe", email="j@x.edu")
        author = user.author_profile
        author.orcid_id = "https://orcid.org/0000-0001-2345-678x"
        author.openalex_ids = ["https://openalex.org/A123", "A456"]
        author.headline = "Structural biologist"
        author.save()
        user.refresh_from_db()
        # Act
        seed = seed_from_user(user)
        # Assert
        self.assertEqual(seed.name, "Jane Doe")
        self.assertEqual(seed.orcid, "0000-0001-2345-678X")
        self.assertEqual(seed.openalex_ids, ("A123", "A456"))
        self.assertIn("https://openalex.org/A123", seed.source_urls)
        self.assertEqual(seed.expertise, "Structural biologist")
        self.assertTrue(seed.is_buildable)


class SeedTests(unittest.TestCase):
    def test_expert_seed_mines_the_orcid_from_sources(self):
        # Arrange
        expert = make_expert(
            affiliation="MIT",
            sources=[{"url": "https://orcid.org/0000-0001-2345-6789"}],
        )
        # Act
        seed = seed_from_expert(expert)
        # Assert
        self.assertEqual(seed.name, "Jane Doe")
        self.assertEqual(seed.affiliation, "MIT")
        self.assertEqual(seed.orcid, "0000-0001-2345-6789")

    def test_merge_prefers_the_users_values_and_unions_urls(self):
        # Arrange
        user_seed = ProfileSeed(name="Jane Doe", source_urls=("https://a",))
        expert_seed = ProfileSeed(
            name="J. Doe",
            affiliation="MIT",
            source_urls=("https://b", "https://a"),
            orcid="0000-0001-2345-6789",
        )
        # Act
        seed = user_seed.merged_over(expert_seed)
        # Assert
        self.assertEqual(seed.name, "Jane Doe")
        self.assertEqual(seed.affiliation, "MIT")
        self.assertEqual(seed.source_urls, ("https://a", "https://b"))
        self.assertEqual(seed.orcid, "0000-0001-2345-6789")

    def test_inputs_hash_tracks_the_seed(self):
        # Arrange
        seed = ProfileSeed(name="Jane Doe")
        # Act & Assert
        self.assertEqual(seed.inputs_hash(), ProfileSeed(name="Jane Doe").inputs_hash())
        self.assertNotEqual(seed.inputs_hash(), ProfileSeed(name="Jo").inputs_hash())

    def test_empty_seed_is_not_buildable(self):
        # Act & Assert
        self.assertFalse(ProfileSeed().is_buildable)
