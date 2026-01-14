from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.sites.models import Site


class OrcidTestHelper:
    """Test helpers for ORCID-related tests."""

    ORCID_ID = "0000-0001-2345-6789"
    ORCID_URL = f"https://orcid.org/{ORCID_ID}"
    OPENALEX_AUTHOR_ID = "https://openalex.org/A5000000001"

    @staticmethod
    def create_app() -> SocialApp:
        """Create ORCID social app for testing."""
        app = SocialApp.objects.create(
            provider=OrcidProvider.id, name="ORCID", client_id="test-id", secret="test-secret"
        )
        app.sites.add(Site.objects.get_current())
        return app
