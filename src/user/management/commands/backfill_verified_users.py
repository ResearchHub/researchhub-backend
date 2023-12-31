from django.core.management.base import BaseCommand, CommandError

from notification.models import Notification
from researchhub_case.models import AuthorClaimCase
from researchhub_case.tasks import after_approval_flow
from researchhub_case.utils.author_claim_case_utils import send_verification_email
from user.models import User


class Command(BaseCommand):
    help = "Backfills verified users"

    def add_arguments(self, parser):
        # Add the --save argument
        parser.add_argument(
            "--save-and-notify",
            action="store_true",
            help="Save the changes to the database",
        )

    def handle(self, *args, **options):
        save_and_notify = options.get("save-and-notify", False)

        approved_claims = AuthorClaimCase.objects.filter(status="APPROVED")
        approved_unique_user_ids = approved_claims.values_list(
            "requestor_id", flat=True
        ).distinct()

        # Print the number of users that will be updated
        self.stdout.write("--------------------------")
        self.stdout.write(
            self.style.SUCCESS(
                f"# Unique users w/approved papers: {len(approved_unique_user_ids)}"
            )
        )

        approved_unique_users_which_arent_verified = []
        for user_id in approved_unique_user_ids:
            user = User.objects.get(pk=user_id)

            if not user.is_verified:
                approved_unique_users_which_arent_verified.append(
                    [
                        user,
                    ]
                )
                print(
                    "Name: "
                    + user.first_name
                    + " "
                    + user.last_name
                    + " | Id: "
                    + str(user.id)
                    + " | Email: "
                    + user.email
                )

        self.stdout.write("--------------------------")

        if save_and_notify:
            self.stdout.write(self.style.SUCCESS("Saving changes..."))

            for user in approved_unique_users_which_arent_verified:
                first_user_claim = AuthorClaimCase.objects.filter(
                    requestor=user, status="APPROVED"
                ).first()

                # Set author profile to verified
                user.is_verified = True
                user.author_profile.is_verified = True
                user.author_profile.save(update_fields=["is_verified"])
                user.save(update_fields=["is_verified"])

                # In-app notification about verification approval
                verification_notification = Notification.objects.create(
                    item=first_user_claim,
                    notification_type=Notification.ACCOUNT_VERIFIED,
                    recipient=user,
                    action_user=user,
                )
                verification_notification.send_notification()
                send_verification_email(first_user_claim, context={})

        self.stdout.write(self.style.SUCCESS("Backfill operation completed."))
