from allauth.account.utils import perform_login
from allauth.socialaccount.helpers import _social_login
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.db.models.signals import post_save, pre_social_login, receiver


@receiver(post_save, sender=SocialAccount, dispatch_uid="link_orcid_account_to_author")
def link_orcid_account_to_author(sender, instance, created, update_fields, **kwargs):
    if (instance.provider == OrcidProvider.id) and (
        created or check_uid_updated(update_fields)
    ):
        author = instance.user.author_profile
        author.orcid_account = instance
        author.save(update_fields=["orcid_account"])


def check_uid_updated(update_fields):
    if update_fields is not None:
        return "uid" in update_fields


@receiver(pre_social_login)
def link_to_existing_user(sender, request, sociallogin, **kwargs):
    user = request.user
    import pdb

    pdb.set_trace()
    if user:
        # If the user exists, connect this new social login to that user
        sociallogin.connect(request, user)
        # Notify the system that we took care of this login attempt
        _social_login(request, sociallogin)
    # No user found, continue with regular login process
