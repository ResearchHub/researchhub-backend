from allauth.account.adapter import DefaultAccountAdapter

from researchhub.settings import BASE_FRONTEND_URL, TESTING


class CustomAccountAdapter(DefaultAccountAdapter):
    def get_email_confirmation_url(self, request, emailconfirmation):
        return f"{BASE_FRONTEND_URL}/verify/{emailconfirmation.key}"
