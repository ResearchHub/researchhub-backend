from time import time

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.orcid.provider import OrcidProvider


class SocialAccountAdapter(DefaultSocialAccountAdapter):
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
