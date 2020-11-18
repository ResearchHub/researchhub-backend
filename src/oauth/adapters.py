from time import time

from allauth.socialaccount import providers
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.google.provider import GoogleProvider
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from google.oauth2 import id_token
from google.auth.transport import requests

from user.models import Author
from user.utils import merge_author_profiles
from utils.siftscience import events_api, update_user_risk_score


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):  # Saves new user
        if sociallogin.account.provider == OrcidProvider.id:
            sociallogin.user.username = self._generate_temporary_username(
                sociallogin
            )
            saved_user = super().save_user(request, sociallogin, form)
            self._merge_or_update_orcid_author(saved_user, sociallogin)
        else:
            saved_user = super().save_user(request, sociallogin, form)

        tracked_account = events_api.track_account(saved_user, request)
        update_user_risk_score(saved_user, tracked_account)
        return saved_user

    def _generate_temporary_username(self, sociallogin):
        return (
            f'{sociallogin.user.first_name}'
            f'_{sociallogin.user.last_name}'
            f'_{time()}'
        )

    def _merge_or_update_orcid_author(self, user, sociallogin):
        orcid_id = sociallogin.account.uid
        try:
            author = Author.objects.get(orcid_id=orcid_id)
        except Author.DoesNotExist:
            self._add_orcid_to_author(user.author_profile, sociallogin.account)
        else:
            user.author_profile = merge_author_profiles(
                user.author_profile,
                author
            )
            user.author_profile.orcid_account = sociallogin.account
            user.author_profile.save()
        user.save()

    def _add_orcid_to_author(self, author_profile, social_account):
        author_profile.orcid_id = social_account.uid
        author_profile.orcid_account = social_account
        author_profile.save()


class GoogleIdTokenProvider(GoogleProvider):

    def extract_uid(self, data):
        return str(data['sub'])


class GoogleOAuth2AdapterIdToken(GoogleOAuth2Adapter):

    def get_provider(self):
        return GoogleIdTokenProvider(self.request)

    def complete_login(self, request, app, token, **kwargs):
        idinfo = id_token.verify_oauth2_token(
            token.token,
            requests.Request(),
            app.client_id
        )
        if idinfo['iss'] not in [
            'accounts.google.com',
            'https://accounts.google.com'
        ]:
            raise ValueError('Wrong issuer.')
        extra_data = idinfo
        login = self.get_provider().sociallogin_from_response(
            request,
            extra_data
        )
        return login
