from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Balance(models.Model):
    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="balances"
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(null=True)
    source = GenericForeignKey("content_type", "object_id")

    # TODO: why is this a char field?
    amount = models.CharField(max_length=255)
    testnet_amount = models.CharField(max_length=255, default=0, null=True, blank=True)

    # Balance locking fields
    is_locked = models.BooleanField(default=False)
    lock_type = models.CharField(
        max_length=50,
        choices=[
            ("FUNDRAISE_CONTRIBUTION", "Fundraise Contribution"),
        ],
        null=True,
        blank=True,
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    @classmethod
    def create_locked_balance(
        cls, user, amount, lock_type="FUNDRAISE_CONTRIBUTION", source=None
    ):
        """Create a locked balance entry for the user using the distributor"""
        from django.utils import timezone

        from reputation.distributions import create_locked_balance_distribution
        from reputation.distributor import Distributor

        # Create distribution for locked balance
        distribution = create_locked_balance_distribution(amount)

        # Use the distributor to create the locked balance record
        distributor = Distributor(
            distribution=distribution,
            recipient=user,
            db_record=source or user,  # Use source if provided, otherwise user
            timestamp=timezone.now().isoformat(),  # Convert to string for JSON serialization
        )

        # Distribute the locked balance
        distribution_record = distributor.distribute_locked_balance(lock_type=lock_type)

        # Return the created balance record
        return cls.objects.get(
            content_type=ContentType.objects.get_for_model(distribution_record),
            object_id=distribution_record.id,
            user=user,
        )
