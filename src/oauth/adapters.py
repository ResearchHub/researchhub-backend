import jwt
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.google.provider import GoogleProvider
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter

from utils.siftscience import events_api, update_user_risk_score


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):  # Saves new user
        saved_user = super().save_user(request, sociallogin, form)

        tracked_account = events_api.track_account(saved_user, request)
        update_user_risk_score(saved_user, tracked_account)
        return saved_user


class GoogleIdTokenProvider(GoogleProvider):
    def extract_uid(self, data):
        return str(data["sub"])


class GoogleOAuth2AdapterIdToken(GoogleOAuth2Adapter):
    def complete_login(self, request, app, token, **kwargs):
        """
        NOTE: this can be confusing due to naming compared to GoogleOAuth2Adapter
        But this is what we have to play with since the payload from Google is different
        """
        user_info = jwt.decode(token, options={"verify_signature": False})
        user_info["id"] = user_info["sub"]
        login = self.get_provider().sociallogin_from_response(
            request,
            user_info,
        )
        return login
