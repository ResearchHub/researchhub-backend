from allauth.account.adapter import DefaultAccountAdapter


class CustomAccountAdapter(DefaultAccountAdapter):
    def get_email_confirmation_url(self, request, emailconfirmation):
        print("++++++++++++++")
        print("++++++++++++++")
        print("++++++++++++++")
        print("++++++++++++++")
        return f"https://mywebsite.com/register/verify/{emailconfirmation.key}"
