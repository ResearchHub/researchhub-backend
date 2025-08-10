from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from analytics.amplitude import UserActivityTypes, track_user_activity

User = get_user_model()


class Command(BaseCommand):
    help = "Test user activity tracking functionality"

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-id",
            type=int,
            help="User ID to test with (optional)",
        )

    def handle(self, *args, **options):
        user_id = options.get("user_id")

        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"User with ID {user_id} does not exist")
                )
                return
        else:
            # Create a test user if none specified
            user, created = User.objects.get_or_create(
                username="test_analytics_user",
                defaults={
                    "email": "test_analytics@example.com",
                    "first_name": "Test",
                    "last_name": "User",
                },
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"Created test user: {user.username}")
                )

        self.stdout.write(f"Testing user activity tracking with user: {user.username}")

        # Test all activity types
        activity_types = [
            UserActivityTypes.UPVOTE,
            UserActivityTypes.COMMENT,
            UserActivityTypes.PEER_REVIEW,
            UserActivityTypes.FUND,
            UserActivityTypes.TIP,
            UserActivityTypes.JOURNAL_SUBMISSION,
        ]

        for activity_type in activity_types:
            self.stdout.write(f"Testing {activity_type}...")

            # Track the activity
            track_user_activity(
                user=user,
                activity_type=activity_type,
                additional_properties={
                    "test": True,
                    "activity_type": activity_type,
                    "user_id": user.id,
                },
            )

            self.stdout.write(self.style.SUCCESS(f"✓ Tracked {activity_type}"))

        self.stdout.write(
            self.style.SUCCESS("User activity tracking test completed successfully!")
        )
