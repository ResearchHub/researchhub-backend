from django.apps import AppConfig


class OAuthConfig(AppConfig):
    """
    Configuration for the OAuth app
    """

    name = "oauth"
    verbose_name = "OAuth"

    def ready(self):
        import oauth.signals  # noqa: F401
