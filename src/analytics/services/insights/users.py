from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount

from user.models import User, UserVerification


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

    orcid_connected = (
        SocialAccount.objects.filter(
            provider="orcid",
            date_joined__gte=period.start,
            date_joined__lt=period.end,
        )
        .values("user_id")
        .distinct()
        .count()
    )

    return {
        "verified_users": UserVerification.objects.filter(
            status=UserVerification.Status.APPROVED,
            updated_date__gte=period.start,
            updated_date__lt=period.end,
        ).count(),
        "orcid_connected": orcid_connected,
        "newly_created": {
            "total": len(new_user_ids),
            "via_email": {
                "total": len(email_user_ids),
                "verified_email": len(verified_email_user_ids),
            },
            "via_google": len(google_user_ids),
        },
    }
