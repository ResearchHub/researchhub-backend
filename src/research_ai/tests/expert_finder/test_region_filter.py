"""Unit tests for expert-finder region → country-code hard filtering."""

from django.test import SimpleTestCase

from research_ai.constants import EXPERT_FINDER_DEFAULT_STATE, Region
from research_ai.services.expert_finder.region_filter import (
    affiliation_mentions_state,
    author_matches_region,
    country_codes_for_region,
    institution_country_codes,
)


class CountryCodesForRegionTests(SimpleTestCase):
    def test_us_and_europe_are_positive_allow_lists(self):
        # Arrange / Act / Assert
        self.assertEqual(country_codes_for_region(Region.US), frozenset({"US"}))
        self.assertIn("DE", country_codes_for_region(Region.EUROPE))
        self.assertIn("GB", country_codes_for_region(Region.EUROPE))
        self.assertIn("JP", country_codes_for_region(Region.ASIA_PACIFIC))
        self.assertIn("EG", country_codes_for_region(Region.AFRICA_MENA))

    def test_all_regions_and_non_us_have_no_allow_list(self):
        # Arrange / Act / Assert
        self.assertIsNone(country_codes_for_region(Region.ALL_REGIONS))
        self.assertIsNone(country_codes_for_region(Region.NON_US))


class InstitutionCountryCodesTests(SimpleTestCase):
    def test_prefers_last_known_institutions(self):
        # Arrange
        record = {
            "last_known_institutions": [
                {"display_name": "MIT", "country_code": "us"},
                {"display_name": "Oxford", "country_code": "GB"},
            ],
            "affiliations": [
                {"institution": {"display_name": "Somewhere", "country_code": "CN"}}
            ],
        }
        # Act / Assert
        self.assertEqual(institution_country_codes(record), {"US", "GB"})

    def test_falls_back_to_affiliations_when_last_known_empty(self):
        # Arrange
        record = {
            "last_known_institutions": [],
            "affiliations": [
                {"institution": {"display_name": "Tokyo U", "country_code": "jp"}}
            ],
        }
        # Act / Assert
        self.assertEqual(institution_country_codes(record), {"JP"})


class AuthorMatchesRegionTests(SimpleTestCase):
    def test_all_regions_always_matches(self):
        # Arrange / Act / Assert
        self.assertTrue(author_matches_region({}, Region.ALL_REGIONS))
        self.assertTrue(author_matches_region(None, Region.ALL_REGIONS))

    def test_us_requires_us_code(self):
        # Arrange
        us = {"last_known_institutions": [{"country_code": "US"}]}
        de = {"last_known_institutions": [{"country_code": "DE"}]}
        # Act / Assert
        self.assertTrue(author_matches_region(us, Region.US))
        self.assertFalse(author_matches_region(de, Region.US))

    def test_non_us_requires_any_non_us_code(self):
        # Arrange
        us_only = {"last_known_institutions": [{"country_code": "US"}]}
        mixed = {
            "last_known_institutions": [
                {"country_code": "US"},
                {"country_code": "FR"},
            ]
        }
        # Act / Assert
        self.assertFalse(author_matches_region(us_only, Region.NON_US))
        self.assertTrue(author_matches_region(mixed, Region.NON_US))

    def test_europe_intersect(self):
        # Arrange
        fr = {"last_known_institutions": [{"country_code": "FR"}]}
        us = {"last_known_institutions": [{"country_code": "US"}]}
        # Act / Assert
        self.assertTrue(author_matches_region(fr, Region.EUROPE))
        self.assertFalse(author_matches_region(us, Region.EUROPE))

    def test_missing_codes_fail_closed(self):
        # Arrange / Act / Assert
        self.assertFalse(author_matches_region({}, Region.US))
        self.assertFalse(
            author_matches_region(
                {"last_known_institutions": [{"display_name": "Unknown"}]},
                Region.EUROPE,
            )
        )


class AffiliationMentionsStateTests(SimpleTestCase):
    def test_default_state_is_not_a_signal(self):
        # Arrange / Act / Assert
        self.assertFalse(
            affiliation_mentions_state(
                "MIT, Cambridge, MA", EXPERT_FINDER_DEFAULT_STATE
            )
        )

    def test_substring_match_is_case_insensitive(self):
        # Arrange / Act / Assert
        self.assertTrue(
            affiliation_mentions_state(
                "University of California, California", "california"
            )
        )
        self.assertFalse(affiliation_mentions_state("MIT", "California"))
