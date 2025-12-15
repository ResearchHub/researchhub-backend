import requests

from allauth.socialaccount.models import SocialApp
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from orcid.services.orcid_service import (
    build_auth_url,
    connect_orcid_account,
    decode_state,
    exchange_code_for_token,
    get_orcid_app,
    get_redirect_url,
)

User = get_user_model()


class OrcidConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            app = get_orcid_app()
            return_url = request.data.get("return_url")
            auth_url = build_auth_url(app, request.user.id, return_url)
            return Response({"auth_url": auth_url})
        except SocialApp.DoesNotExist:
            return Response({"error": "ORCID not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            return Response({"error": "Failed to initiate ORCID connection"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class OrcidCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.query_params.get("code")
        state = request.query_params.get("state", "")

        if request.query_params.get("error") or not code:
            return redirect(get_redirect_url(error="cancelled"))

        state_data = decode_state(state)
        if not state_data:
            return redirect(get_redirect_url(error="invalid_state"))

        user_id = state_data.get("user_id")
        return_url = state_data.get("return_url")

        try:
            user = User.objects.get(id=user_id)
            app = get_orcid_app()
            token_data = exchange_code_for_token(app, code)
            with transaction.atomic():
                connect_orcid_account(user, token_data, app)
            return redirect(get_redirect_url(return_url=return_url))
        except User.DoesNotExist:
            return redirect(get_redirect_url(error="This User Does Not Exist", return_url=return_url))
        except ValueError:
            return redirect(get_redirect_url(error="This ORCID ID Is Already Linked", return_url=return_url))
        except (requests.RequestException, SocialApp.DoesNotExist):
            return redirect(get_redirect_url(error="This ORCID ID Is Not Valid", return_url=return_url))
