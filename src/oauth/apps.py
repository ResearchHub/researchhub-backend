from django.apps import AppConfig


class OAuthConfig(AppConfig):
    """
    Configuration for the OAuth app

    Set the OAUTH_METHOD variable in the project's settings.py to
    'token' to send Django Rest Framework tokens upon login.

    Otherwise, successfull logins will redirect to the url set by
    LOGIN_REDIRECT_URL.
    """
    name = 'oauth'
    verbose_name = 'OAuth'
