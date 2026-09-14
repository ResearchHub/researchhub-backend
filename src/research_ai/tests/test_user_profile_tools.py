import json
from types import SimpleNamespace

from django.test import SimpleTestCase

from research_ai.services.user_profile_tools import (
    GET_USER_PROFILE,
    UserProfileToolset,
)


class UserProfileToolsetTests(SimpleTestCase):
    def test_returns_public_profile_and_normalized_pages(self):
        # Arrange
        author = SimpleNamespace(
            id=42,
            first_name="Ada",
            last_name="Lovelace",
            headline="Research scientist",
            description="Studies analytical engines.",
            university=SimpleNamespace(name="Example University", city="London"),
            country_code="GB",
            education=[{"institution": "Example College"}],
            h_index=12,
            i10_index=7,
            two_year_mean_citedness=2.5,
            orcid_id="https://orcid.org/0000-0001-2345-6789",
            openalex_ids=["A123", "https://api.openalex.org/authors/A456/"],
            linkedin="https://www.linkedin.com/in/ada",
            google_scholar="https://scholar.google.com/citations?user=ada",
            twitter="https://x.com/ada",
            facebook=None,
        )
        user = SimpleNamespace(
            first_name="Account",
            last_name="Name",
            email="private@example.com",
            author_profile=author,
        )
        toolset = UserProfileToolset(user=user).as_toolset()

        # Act
        result, stop = toolset.dispatch(GET_USER_PROFILE, {})

        # Assert
        self.assertFalse(stop)
        self.assertEqual(result["name"], "Ada Lovelace")
        self.assertEqual(result["identifiers"]["orcid"], "0000-0001-2345-6789")
        self.assertEqual(
            result["links"]["orcid"],
            "https://orcid.org/0000-0001-2345-6789",
        )
        self.assertEqual(
            result["links"]["openalex"],
            ["https://openalex.org/A123", "https://openalex.org/A456"],
        )
        self.assertEqual(result["links"]["linkedin"], "https://www.linkedin.com/in/ada")
        self.assertIn("/user/42/overview", result["links"]["researchhub"])
        self.assertEqual(result["profile"]["affiliation"]["city"], "London")
        self.assertNotIn("private@example.com", str(result))

    def test_bounds_each_education_entry_before_dispatch(self):
        # Arrange
        author = SimpleNamespace(
            id=42,
            first_name="Ada",
            last_name="Lovelace",
            headline=None,
            description=None,
            university=None,
            country_code=None,
            education=[
                {
                    "institution": "Huge University",
                    "details": "🔬" * (128 * 1024),
                },
                {"institution": "Small College"},
            ],
            h_index=0,
            i10_index=0,
            two_year_mean_citedness=0,
            orcid_id=None,
            openalex_ids=[],
            linkedin=None,
            google_scholar=None,
            twitter=None,
            facebook=None,
        )
        user = SimpleNamespace(
            first_name="Ada",
            last_name="Lovelace",
            author_profile=author,
        )

        # Act
        result, stop = (
            UserProfileToolset(user=user).as_toolset().dispatch(GET_USER_PROFILE, {})
        )

        # Assert
        self.assertFalse(stop)
        self.assertNotIn("error", result)
        education = result["profile"]["education"]
        self.assertTrue(education[0]["truncated"])
        self.assertGreater(education[0]["original_size_bytes"], 128 * 1024)
        self.assertLessEqual(len(json.dumps(education[0]).encode("utf-8")), 2048)
        self.assertEqual(education[1], {"institution": "Small College"})
        self.assertLess(len(json.dumps(result).encode("utf-8")), 128 * 1024)

    def test_returns_account_name_when_author_profile_is_missing(self):
        # Arrange
        user = SimpleNamespace(
            first_name="Grace",
            last_name="Hopper",
            author_profile=None,
        )

        # Act
        result, stop = (
            UserProfileToolset(user=user).as_toolset().dispatch(GET_USER_PROFILE, {})
        )

        # Assert
        self.assertFalse(stop)
        self.assertEqual(
            result,
            {
                "name": "Grace Hopper",
                "profile": None,
                "identifiers": {},
                "links": {},
            },
        )
