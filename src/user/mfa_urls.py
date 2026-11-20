from dj_rest_auth.mfa.views import MFAStatusView, MFAVerifyView
from django.urls import re_path

from user.views.mfa_views import (
    PasswordConfirmedTOTPActivateView,
    ThrottledTOTPDeactivateView,
    TOTPConfirmedRecoveryCodesRegenerateView,
    TOTPConfirmedRecoveryCodesView,
)

urlpatterns = [
    re_path(r"^mfa/verify/?$", MFAVerifyView.as_view(), name="mfa_verify"),
    re_path(
        r"^mfa/totp/activate/?$",
        PasswordConfirmedTOTPActivateView.as_view(),
        name="mfa_totp_activate",
    ),
    re_path(
        r"^mfa/totp/deactivate/?$",
        ThrottledTOTPDeactivateView.as_view(),
        name="mfa_totp_deactivate",
    ),
    re_path(r"^mfa/status/?$", MFAStatusView.as_view(), name="mfa_status"),
    re_path(
        r"^mfa/recovery-codes/?$",
        TOTPConfirmedRecoveryCodesView.as_view(),
        name="mfa_recovery_codes",
    ),
    re_path(
        r"^mfa/recovery-codes/regenerate/?$",
        TOTPConfirmedRecoveryCodesRegenerateView.as_view(),
        name="mfa_recovery_codes_regenerate",
    ),
]
