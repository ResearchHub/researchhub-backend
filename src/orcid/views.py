import requests

from allauth.socialaccount.models import SocialApp
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from orcid.services.orcid_service import (
    build_auth_url,
    connect_orcid_account,
    exchange_code_for_token,
    get_orcid_app,
    is_orcid_connected,
)
from orcid.tasks import fetch_orcid_works_task


class OrcidConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            app = get_orcid_app()
        except SocialApp.DoesNotExist:
            return Response({"error": "ORCID not configured"}, status=500)

        auth_url = build_auth_url(app, request.user.id)
        return Response({"auth_url": auth_url})


class OrcidCallbackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        code = request.data.get("code")
        state = request.data.get("state", "")

        if not code:
            return Response({"error": "Authorization cancelled"}, status=400)
        if str(request.user.id) != state:
            return Response({"error": "Invalid session"}, status=400)

        try:
            app = get_orcid_app()
            with transaction.atomic():
                token_data = exchange_code_for_token(app, code)
                connect_orcid_account(request.user, token_data)
            try:
                author_id = request.user.author_profile.id
            except AttributeError:
                author_id = None
            return Response({"success": True, "author_id": author_id})
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        except (requests.RequestException, SocialApp.DoesNotExist):
            return Response({"error": "ORCID service error"}, status=500)


class OrcidFetchView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_orcid_connected(request.user):
            return Response({"error": "ORCID not connected"}, status=400)

        try:
            author = request.user.author_profile
        except AttributeError:
            return Response({"error": "Author profile not found"}, status=400)

        fetch_orcid_works_task.delay(author.id)
        return Response({"success": True, "message": "Paper sync started"})

