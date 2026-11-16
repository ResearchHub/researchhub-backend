from dataclasses import asdict

from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from oauth.services.authorization_server_service import OAuthAuthorizationServerService


class ConnectedAppViewSet(ViewSet):
    """
    Lists the OAuth clients the signed-in user has authorized, and revokes them.
    """

    def list(self, request):
        apps = OAuthAuthorizationServerService().list_connected_apps(request.user)
        return Response([asdict(app) for app in apps])

    def destroy(self, request, pk=None):
        # Also succeeds for a client that isn't connected, so repeating it is harmless
        OAuthAuthorizationServerService().revoke_user_tokens(
            request.user, application_id=pk
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
