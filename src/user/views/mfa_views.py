from dj_rest_auth.mfa.views import (
    RecoveryCodesRegenerateView,
    RecoveryCodesView,
    TOTPActivateView,
    TOTPDeactivateView,
)
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework.throttling import UserRateThrottle

from user.mfa_serializers import (
    PasswordConfirmedTOTPActivateSerializer,
    TOTPCodeConfirmationSerializer,
)


class MFAChangeThrottle(UserRateThrottle):
    scope = "mfa_change"
    rate = "10/hour"


class MFAChangeThrottleMixin:
    def get_throttles(self):
        if self.request.method == "POST":
            return [MFAChangeThrottle()]
        return super().get_throttles()


class PasswordConfirmedTOTPActivateView(MFAChangeThrottleMixin, TOTPActivateView):
    def get_serializer_class(self):
        if self.request.method == "POST":
            return PasswordConfirmedTOTPActivateSerializer
        return super().get_serializer_class()


class ThrottledTOTPDeactivateView(MFAChangeThrottleMixin, TOTPDeactivateView):
    pass


class TOTPConfirmedRecoveryCodesMixin(MFAChangeThrottleMixin):
    def post(self, request, *args, **kwargs):
        serializer = TOTPCodeConfirmationSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        return super().post(request, *args, **kwargs)


@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class TOTPConfirmedRecoveryCodesView(
    TOTPConfirmedRecoveryCodesMixin, RecoveryCodesView
):
    pass


@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class TOTPConfirmedRecoveryCodesRegenerateView(
    TOTPConfirmedRecoveryCodesMixin, RecoveryCodesRegenerateView
):
    pass
