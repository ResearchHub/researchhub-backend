from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount

from user.models import Author, User, UserVerification


def get_user_metrics(period):
    new_users = User.objects.filter(
        date_joined__gte=period.start,
        date_joined__lt=period.end,
    )
    new_user_ids = set(new_users.values_list("id", flat=True))
    google_user_ids = set(
        SocialAccount.objects.filter(
            user_id__in=new_user_ids,
            provider="google",
        ).values_list("user_id", flat=True)
    )
    verified_email_user_ids = set(
        EmailAddress.objects.filter(
            user_id__in=new_user_ids - google_user_ids,
            verified=True,
        ).values_list("user_id", flat=True)
    )
    email_user_ids = new_user_ids - google_user_ids

    author_orcid_user_ids = (
        Author.objects.filter(
            user_id__isnull=False,
            orcid_id__isnull=False,
        )
        .exclude(orcid_id="")
        .values_list("user_id", flat=True)
    )
    social_orcid_user_ids = SocialAccount.objects.filter(provider="orcid").values_list(
        "user_id", flat=True
    )
    orcid_connected = len(set(author_orcid_user_ids) | set(social_orcid_user_ids))

    return {
        "verified_users": UserVerification.objects.filter(
            status=UserVerification.Status.APPROVED,
            updated_date__gte=period.start,
            updated_date__lt=period.end,
        ).count(),
        "orcid_connected": orcid_connected,
        "social_accounts_added": SocialAccount.objects.filter(
            date_joined__gte=period.start,
            date_joined__lt=period.end,
        ).count(),
        "newly_created": {
            "total": len(new_user_ids),
            "via_email": {
                "total": len(email_user_ids),
                "verified_email": len(verified_email_user_ids),
            },
            "via_google": len(google_user_ids),
        },
    }
