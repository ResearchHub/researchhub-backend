from allauth.account.adapter import DefaultAccountAdapter, get_adapter
from allauth.account.forms import ResetPasswordForm
from allauth.account.utils import user_pk_to_url_str
from dj_rest_auth.serializers import PasswordResetSerializer
from django.conf import settings


class CustomAccountAdapter(DefaultAccountAdapter):
    def get_email_confirmation_url(self, request, emailconfirmation):
        # TEMPORARY:
        # Use hard-coded URL pointing to the new web application for email confirmation.
        # Will be replaced with `BASE_FRONTEND_URL` after moving the new web application to www.
        base_url = settings.BASE_FRONTEND_URL
        if settings.PRODUCTION:
            base_url = "https://new.researchhub.com"
        elif settings.STAGING:
            base_url = "https://v2.staging.researchhub.com"

        return f"{base_url}/verify/{emailconfirmation.key}"


class CustomPasswordResetSerializer(PasswordResetSerializer):
    @property
    def password_reset_form_class(self):
        return CustomResetPasswordForm

    def get_email_options(self):
        return {
            "email_template": "account/registration/reset",
            "extra_email_context": {},
        }


class CustomResetPasswordForm(ResetPasswordForm):
    def save(self, request, **kwargs):
        email = self.cleaned_data["email"]
        token_generator = kwargs.get("token_generator")
        template = kwargs.get("email_template")
        for user in self.users:
            uid = user_pk_to_url_str(user)
            token = token_generator.make_token(user)
            reset_url = f"{settings.BASE_FRONTEND_URL}/reset/{uid}/{token}"
            context = {
                "assets_base_url": settings.ASSETS_BASE_URL,
                "user": user,
                "request": request,
                "email": email,
                "reset_url": reset_url,
            }
            get_adapter(request).send_mail(template, email, context)
        return email
