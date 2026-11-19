from dj_rest_auth.views import PasswordChangeView
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from user.services.auth_token_service import AuthTokenService


class PasswordChangeThrottle(UserRateThrottle):
    scope = "password_change"
    rate = "10/hour"


class TokenReplacingPasswordChangeView(PasswordChangeView):
    throttle_classes = [PasswordChangeThrottle]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            serializer.save()
            token = AuthTokenService().replace(request.user)
        return Response({"detail": _("New password has been saved."), "key": token.key})
