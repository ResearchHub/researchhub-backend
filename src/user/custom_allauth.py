from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.forms import ResetPasswordForm
from allauth.account.utils import user_pk_to_url_str
from dj_rest_auth.serializers import PasswordResetSerializer
from django.conf import settings
from django.http import HttpRequest
from django.utils.safestring import mark_safe

from mailing_list.lib import send_email

BRANDED_TEMPLATE = "general_branded_email.html"


class CustomAccountAdapter(DefaultAccountAdapter):
    def get_email_confirmation_url(self, request: HttpRequest, emailconfirmation) -> str:
        return f"{settings.BASE_FRONTEND_URL}/verify/{emailconfirmation.key}"

    def send_confirmation_mail(self, request: HttpRequest, emailconfirmation, signup: bool) -> None:
        activate_url = self.get_email_confirmation_url(request, emailconfirmation)
        subject = "Confirm Your Email Address"
        send_email(
            emailconfirmation.email_address.email,
            None,
            subject,
            {
                "body": mark_safe(
                    "<p>Hello from ResearchHub,</p>"
                    "<p>Click the button below to confirm your email address.</p>"
                ),
                "cta_url": activate_url,
                "cta_label": "Confirm Email",
                "subject": subject,
                "assets_base_url": settings.ASSETS_BASE_URL,
            },
            html_template=BRANDED_TEMPLATE,
        )


class CustomPasswordResetSerializer(PasswordResetSerializer):
    @property
    def password_reset_form_class(self):
        return CustomResetPasswordForm

    def get_email_options(self) -> dict:
        return {}


class CustomResetPasswordForm(ResetPasswordForm):
    def save(self, request: HttpRequest, **kwargs) -> str:
        email = self.cleaned_data["email"]
        token_generator = kwargs.get("token_generator")
        for user in self.users:
            uid = user_pk_to_url_str(user)
            token = token_generator.make_token(user)
            reset_url = f"{settings.BASE_FRONTEND_URL}/reset/{uid}/{token}"
            subject = "Reset Your Password"
            send_email(
                email,
                None,
                subject,
                {
                    "body": mark_safe(
                        "<p>Hello from ResearchHub,</p>"
                        "<p>Click the button below to complete "
                        "your password reset.</p>"
                    ),
                    "cta_url": reset_url,
                    "cta_label": "Reset Password",
                    "subject": subject,
                    "assets_base_url": settings.ASSETS_BASE_URL,
                },
                html_template=BRANDED_TEMPLATE,
            )
        return email
