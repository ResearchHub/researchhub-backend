from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.sites.models import Site

TEST_ORCID_ID = "0000-0001-2345-6789"


def create_orcid_app() -> SocialApp:
    app = SocialApp.objects.create(
        provider=OrcidProvider.id, name="ORCID", client_id="test-id", secret="test-secret"
    )
    app.sites.add(Site.objects.get_current())
    return app
