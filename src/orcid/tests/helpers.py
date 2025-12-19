from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.sites.models import Site

from user.tests.helpers import create_random_default_user


class OrcidTestHelper:
    """Test helpers for ORCID-related tests."""

    ORCID_ID = "0000-0001-2345-6789"
    ORCID_URL = f"https://orcid.org/{ORCID_ID}"

    @staticmethod
    def create_author(name: str = "u"):
        """Create a user with ORCID connected to their author profile."""
        user = create_random_default_user(name)
        user.author_profile.orcid_id = OrcidTestHelper.ORCID_URL
        user.author_profile.save()
        return user

    @staticmethod
    def create_app() -> SocialApp:
        """Create ORCID social app for testing."""
        app = SocialApp.objects.create(
            provider=OrcidProvider.id, name="ORCID", client_id="test-id", secret="test-secret"
        )
        app.sites.add(Site.objects.get_current())
        return app

    @staticmethod
    def make_works_response(*dois: str) -> dict:
        """Build an ORCID works API response with the given DOIs."""
        return {
            "group": [
                {"work-summary": [{"external-ids": {"external-id": [
                    {"external-id-type": "doi", "external-id-value": doi}
                ]}}]}
                for doi in dois
            ]
        }

    @staticmethod
    def make_openalex_work(doi: str, orcid_url: str = None, position: str = "first") -> dict:
        """Build an OpenAlex work response."""
        return {
            "doi": f"https://doi.org/{doi}",
            "authorships": [{"author": {"orcid": orcid_url or OrcidTestHelper.ORCID_URL}, "author_position": position}],
        }

