from allauth.account.adapter import DefaultAccountAdapter, get_adapter
from allauth.account.forms import ResetPasswordForm
from allauth.account.utils import user_pk_to_url_str
from dj_rest_auth.registration.serializers import RegisterSerializer
from dj_rest_auth.serializers import PasswordResetSerializer

from researchhub.settings import BASE_FRONTEND_URL, TESTING


class CustomAccountAdapter(DefaultAccountAdapter):
    def get_email_confirmation_url(self, request, emailconfirmation):
        return f"{BASE_FRONTEND_URL}/verify/{emailconfirmation.key}"


# serializers.py
class CustomPasswordResetSerializer(PasswordResetSerializer):
    @property
    def password_reset_form_class(self):
        return CustomResetPasswordForm

    def get_email_options(self):
        return {
            "email_template": "account/registration/reset",
            "extra_email_context": {"client_app": "test"},
        }


class CustomResetPasswordForm(ResetPasswordForm):
    def save(self, request, **kwargs):
        email = self.cleaned_data["email"]
        token_generator = kwargs.get("token_generator")
        template = kwargs.get("email_template")
        for user in self.users:
            uid = user_pk_to_url_str(user)
            print("uid", uid)
            token = token_generator.make_token(user)
            reset_url = f"{BASE_FRONTEND_URL}/reset/{uid}/{token}"
            context = {
                "user": user,
                "request": request,
                "email": email,
                "reset_url": reset_url,
            }
            get_adapter(request).send_mail(template, email, context)
        return email
