from django.core.management.base import BaseCommand

from reputation.tasks import burn_revenue_rsc


class Command(BaseCommand):
    help = "Manually execute the RSC burning task"

    def handle(self, *args, **options):
        self.stdout.write("Starting manual RSC burning...")

        try:
            burn_revenue_rsc()
            self.stdout.write(self.style.SUCCESS("Successfully completed RSC burning"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to burn RSC: {e}"))
