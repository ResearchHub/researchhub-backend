from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):  # Saves new user
        saved_user = super().save_user(request, sociallogin, form)

        return saved_user
