from time import time

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.orcid.provider import OrcidProvider


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        if sociallogin.account.provider == OrcidProvider.id:
            sociallogin.user.username = self._generate_temporary_username(
                sociallogin
            )
            saved_user = super().save_user(request, sociallogin, form)
            self._add_orcid_to_author(
                saved_user.author_profile,
                sociallogin.account
            )
        else:  # It's google
            saved_user = super().save_user(request, sociallogin, form)

        return saved_user

    def _generate_temporary_username(self, sociallogin):
        return (
            f'{sociallogin.user.first_name}'
            f'_{sociallogin.user.last_name}'
            f'_{time()}'
        )

    def _add_orcid_to_author(self, author_profile, social_account):
        author_profile.orcid_id = social_account.uid
        author_profile.orcid_account = social_account
        author_profile.save()
