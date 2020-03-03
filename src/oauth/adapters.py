from time import time

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.orcid.provider import OrcidProvider

from user.models import Author
from user.utils import merge_author_profiles


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
