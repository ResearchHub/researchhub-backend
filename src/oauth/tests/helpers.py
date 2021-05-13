from allauth.socialaccount.models import SocialAccount


def create_social_account(provider, user, uid=None):
    if uid is None:
        uid = provider + str(user.id)
    return SocialAccount.objects.create(
        provider=provider,
        user=user,
        uid=uid
    )
