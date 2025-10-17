from django.core.management.base import BaseCommand
from django.db import transaction

from user.rsc_exchange_rate_record_tasks import rsc_exchange_rate_record_tasks


class Command(BaseCommand):
    help = "Refresh RSC exchange rate data from CoinGecko API"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Fetching RSC exchange rate from CoinGecko...")

        try:
            result = rsc_exchange_rate_record_tasks()

            if result:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully refreshed exchange rate:\n${result['rate']:.6f} USD per RSC"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR("Failed to fetch exchange rate data")
                )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating exchange rate:\n{e}"))
