from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.sites.models import Site


def create_orcid_app() -> SocialApp:
    app = SocialApp.objects.create(
        provider=OrcidProvider.id,
        name="ORCID",
        client_id="test-id",
        secret="test-secret",
    )
    app.sites.add(Site.objects.get_current())
    return app
