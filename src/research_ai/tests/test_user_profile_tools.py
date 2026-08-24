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
