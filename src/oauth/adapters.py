from time import time

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.provider import GoogleProvider
from allauth.socialaccount.providers.orcid.provider import OrcidProvider


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        email = sociallogin.user.email
        if email:
            other_provider = OrcidProvider.id
            if sociallogin.account.provider == OrcidProvider.id:
                other_provider = GoogleProvider.id
            try:
                if SocialAccount.objects.get(
                    user__email=email,
                    provider=other_provider
                ).exists():
                    sociallogin.state['process'] = 'connect'
            except Exception as e:
                print(e)

        return super().pre_social_login(request, sociallogin)

    def save_user(self, request, sociallogin, form=None):
        if sociallogin.account.provider == OrcidProvider.id:
            sociallogin.user.username = self._generate_temporary_username(
                sociallogin
            )
        return super().save_user(request, sociallogin, form)

    def _generate_temporary_username(self, sociallogin):
        return (
            f'{sociallogin.user.first_name}'
            f'_{sociallogin.user.last_name}'
            f'_{time()}'
        )
