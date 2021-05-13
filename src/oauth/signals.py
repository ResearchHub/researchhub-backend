from django.db.models.signals import post_save, receiver
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider


@receiver(
    post_save,
    sender=SocialAccount,
    dispatch_uid='link_orcid_account_to_author'
)
def link_orcid_account_to_author(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if (
        (instance.provider == OrcidProvider.id)
        and (created or check_uid_updated(update_fields))
    ):
        author = instance.user.author_profile
        author.orcid_account = instance
        author.save(update_fields=['orcid_account'])


def check_uid_updated(update_fields):
    if update_fields is not None:
        return 'uid' in update_fields
