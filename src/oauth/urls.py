from django.urls import path
from oauth2_provider.views import RevokeTokenView, TokenView

from oauth.views import AuthorizationServerMetadataView, oauth_enabled

# DOT's metadata view finds endpoints by reversing names in its own namespace
app_name = "oauth2_provider"

urlpatterns = [
    path(
        ".well-known/oauth-authorization-server",
        oauth_enabled(AuthorizationServerMetadataView.as_view()),
        name="oauth-server-metadata",
    ),
    path(
        "oauth/token/",
        oauth_enabled(TokenView.as_view()),
        name="token",
    ),
    path(
        "oauth/revoke/",
        oauth_enabled(RevokeTokenView.as_view()),
        name="revoke-token",
    ),
]
