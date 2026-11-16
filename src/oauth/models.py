from django.db import models
from oauth2_provider.settings import oauth2_settings


class DelegatedAccessToken(models.Model):
    """
    Links an access token issued by a token exchange to the token it was exchanged for.
    Revoking the source token deletes the link, and API authentication requires it,
    so the issued token stops working too.
    """

    access_token = models.OneToOneField(
        oauth2_settings.ACCESS_TOKEN_MODEL,
        on_delete=models.CASCADE,
        related_name="delegation",
    )
    source_token = models.ForeignKey(
        oauth2_settings.ACCESS_TOKEN_MODEL,
        on_delete=models.CASCADE,
        related_name="delegated_tokens",
    )
