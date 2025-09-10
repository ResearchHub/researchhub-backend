"""
Process deposits with configurable TTL.

This script allows processing deposits with a custom TTL value
by passing it as a parameter to the _check_deposits() function.
"""

from datetime import datetime

import pytz
from django.core.management.base import BaseCommand

from reputation import tasks
from reputation.models import Deposit
from user.models import User


class Command(BaseCommand):
    help = "Process deposits with configurable TTL"

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-id",
            type=int,
            help="User ID for new deposit (required when creating a deposit)",
            required=True,
        )
        parser.add_argument(
            "--transaction-hash",
            type=str,
            help="Transaction hash for new deposit (required when creating a deposit)",
            required=True,
        )
        parser.add_argument(
            "--from-address",
            type=str,
            help="From address for new deposit (required when creating a deposit)",
            required=True,
        )
        parser.add_argument(
            "--amount",
            type=str,
            help="Deposit amount (optional, defaults to 0.0 and will be updated when processed)",
            required=True,
        )
        parser.add_argument(
            "--network",
            type=str,
            choices=["BASE", "ETHEREUM"],
            help="Network for new deposit",
            required=True,
        )

    def handle(self, *args, **options):
        user_id = options.get("user_id")
        transaction_hash = options.get("transaction_hash")
        from_address = options.get("from_address")
        amount = options.get("amount")
        network = options.get("network")
        max_age_seconds = int(10 * 365 * 24 * 60 * 60)  # 10 years in seconds

        user = User.objects.get(id=user_id)

        Deposit.objects.create(
            user=user,
            amount=amount,
            from_address=from_address,
            transaction_hash=transaction_hash,
            network=network,
        )

        tasks.check_deposits(max_age=max_age_seconds)
