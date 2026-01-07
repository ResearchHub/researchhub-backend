from django.shortcuts import redirect
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.views import APIView

from orcid.services import OrcidCallbackService


class OrcidCallbackView(APIView):
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        self.orcid_callback_service = kwargs.pop("orcid_callback_service", OrcidCallbackService())
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: Request):
        """Handle ORCID OAuth callback redirect."""
        error = request.query_params.get("error")
        code = request.query_params.get("code")

        if error or not code:
            return redirect(self.orcid_callback_service.get_redirect_url(error="cancelled"))

        state = request.query_params.get("state", "")
        return redirect(self.orcid_callback_service.process_callback(code=code, state=state))
