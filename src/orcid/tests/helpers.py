from allauth.socialaccount.models import SocialAccount, SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.sites.models import Site

from user.models import User
from user.tests.helpers import create_random_default_user


class OrcidTestHelper:
    """Test helpers for ORCID-related tests."""

    ORCID_ID = "0000-0001-2345-6789"
    ORCID_URL = f"https://orcid.org/{ORCID_ID}"

    @staticmethod
    def create_connected_user() -> User:
        """Create a user whose author profile is connected to ORCID."""
        user = create_random_default_user("u")
        user.author_profile.orcid_id = OrcidTestHelper.ORCID_URL
        user.author_profile.save()
        SocialAccount.objects.create(
            user=user,
            provider=OrcidProvider.id,
            uid=OrcidTestHelper.ORCID_ID,
        )
        return user

    @staticmethod
    def create_app() -> SocialApp:
        """Create ORCID social app for testing."""
        app = SocialApp.objects.create(
            provider=OrcidProvider.id,
            name="ORCID",
            client_id="test-id",
            secret="test-secret",
        )
        app.sites.add(Site.objects.get_current())
        return app
