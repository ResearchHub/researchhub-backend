from allauth.socialaccount.models import SocialApp
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from requests.exceptions import RequestException
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.views import APIView

from orcid.services.orcid_service import OrcidService

User = get_user_model()


class OrcidCallbackView(APIView):
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        self.orcid_service = OrcidService()
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: Request, *args, **kwargs) -> HttpResponseRedirect:
        code = request.query_params.get("code")
        state = request.query_params.get("state", "")

        if request.query_params.get("error") or not code:
            return redirect(self.orcid_service.get_redirect_url(error="cancelled"))

        state_data = self.orcid_service.decode_state(state)
        if not state_data:
            return redirect(self.orcid_service.get_redirect_url(error="invalid_state"))

        user_id = state_data.get("user_id")
        return_url = state_data.get("return_url")

        try:
            user = User.objects.get(id=user_id)
            token_data = self.orcid_service.exchange_code_for_token(code)
            self.orcid_service.connect_orcid_account(user, token_data)
            return redirect(self.orcid_service.get_redirect_url(return_url=return_url))
        except User.DoesNotExist:
            return redirect(self.orcid_service.get_redirect_url(error="invalid_state", return_url=return_url))
        except ValueError:
            return redirect(self.orcid_service.get_redirect_url(error="already_linked", return_url=return_url))
        except (RequestException, SocialApp.DoesNotExist):
            return redirect(self.orcid_service.get_redirect_url(error="service_error", return_url=return_url))
