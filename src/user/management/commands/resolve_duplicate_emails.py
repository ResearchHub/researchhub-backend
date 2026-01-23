from allauth.account.models import EmailAddress
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.db.models.functions import Lower


class Command(BaseCommand):
    help = "Clean up duplicate email addresses that differ by case"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write("*** DRY RUN ***\n")

        duplicates = (
            EmailAddress.objects.annotate(lower_email=Lower("email"))
            .values("lower_email")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
        )

        total_duplicates = duplicates.count()
        self.stdout.write(f"Found {total_duplicates} sets of duplicate emails\n")

        deleted_count = 0
        kept_count = 0

        for dupe in duplicates:
            lower_email = dupe["lower_email"]

            # Order by: verified, then by Id (highest/newest first)
            addresses = list(
                EmailAddress.objects.annotate(lower_email=Lower("email"))
                .filter(lower_email=lower_email)
                .select_related("user")
                .order_by("-verified", "-id")
            )

            if len(addresses) > 1:
                keep = addresses[0]
                to_delete = addresses[1:]

                self.stdout.write(f"\nDuplicates for: {lower_email}")
                self.stdout.write(
                    f"  KEEP: {keep.email} (user_id={keep.user_id}, "
                    f"verified={keep.verified}, id={keep.id})"
                )

                for addr in to_delete:
                    self.stdout.write(
                        f"  DELETE: {addr.email} (user_id={addr.user_id}, "
                        f"verified={addr.verified}, id={addr.id})"
                    )
                    if not dry_run:
                        addr.delete()
                    deleted_count += 1

                kept_count += 1

        self.stdout.write("")

        self.stdout.write(
            f"Resolved duplicates: kept {kept_count}, deleted {deleted_count}"
        )
