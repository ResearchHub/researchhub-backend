import hashlib

from django.core.management.base import BaseCommand
from mailchimp_marketing import Client
from mailchimp_marketing.api_client import ApiClientError

from researchhub.settings import MAILCHIMP_LIST_ID, MAILCHIMP_SERVER, keys
from user.models import User


class Command(BaseCommand):
    help = "Remove spammers and inactive users from Mailchimp"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform a dry run without actually removing users from Mailchimp",
        )
        parser.add_argument(
            "--permanent-delete",
            action="store_true",
            help="Permanently delete contacts (instead of archiving)",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        permanent_delete = options.get("permanent_delete", False)

        mailchimp = Client()
        mailchimp.set_config(
            {
                "api_key": keys.MAILCHIMP_KEY,
                "server": MAILCHIMP_SERVER,
            }
        )

        # Get users to be removed
        users_to_remove = (
            User.objects.filter(probable_spammer=True)
            | User.objects.filter(is_active=False)
            | User.objects.filter(is_suspended=True)
        )

        total_count = users_to_remove.count()
        removed_count = 0
        error_count = 0

        action_type = "permanent deletion" if permanent_delete else "archival"
        self.stdout.write(f"Found {total_count} users for {action_type} from Mailchimp")

        if dry_run:
            self.stdout.write("DRY RUN - No actual changes are made")

        if permanent_delete:
            self.stdout.write(
                self.style.WARNING("\nWARNING: Permanent deletion active!")
            )

        for i, user in enumerate(users_to_remove):
            email = user.email.lower()
            email_hash = hashlib.md5(email.encode()).hexdigest()

            self.stdout.write(f"Processing {i + 1}/{total_count}: {email}")

            if not dry_run:
                try:
                    if permanent_delete:
                        # Permanently delete contact
                        mailchimp.lists.delete_list_member_permanent(
                            MAILCHIMP_LIST_ID, email_hash
                        )
                        removed_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  ✓ Permanently deleted {email} from Mailchimp"
                            )
                        )
                    else:
                        # Archive user from Mailchimp list (can be unarchived)
                        mailchimp.lists.delete_list_member(
                            MAILCHIMP_LIST_ID, email_hash
                        )
                        removed_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"  ✓ Archived {email} from Mailchimp")
                        )
                except ApiClientError as error:
                    error_count += 1
                    error_detail = error.text if hasattr(error, "text") else str(error)

                    # User not found
                    if "404" in str(error):
                        self.stdout.write(
                            self.style.WARNING(
                                f"  ⚠ {email} not found in Mailchimp list"
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  ✗ Error removing {email}: {error_detail}"
                            )
                        )
                except Exception as error:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"  ✗ Unexpected error for {email}: {str(error)}"
                        )
                    )
            else:
                action = "permanently delete" if permanent_delete else "archive"
                self.stdout.write(f"  → Would {action} {email} from Mailchimp")

        # Create summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(f"Total users processed: {total_count}")

        if not dry_run:
            action_past = "Permanently deleted" if permanent_delete else "Archived"
            self.stdout.write(self.style.SUCCESS(f"{action_past}: {removed_count}"))
            self.stdout.write(self.style.ERROR(f"Errors: {error_count}"))
        else:
            self.stdout.write("DRY RUN completed - no changes were made")
