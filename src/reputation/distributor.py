from django.contrib.admin.options import get_content_type_for_model
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction

import utils.sentry as sentry
from purchase.models import Balance
from reputation.exceptions import ReputationDistributorError
from reputation.models import Distribution
from user.models import User
from utils.serializers import get_model_serializer


class Distributor:
    """
    Distributes an amount to the request user's reputation and logs this event
    by creating an Distribution record in the database.

    Args:
        distribution (obj) - Distribution class object
        recipient (obj) - User receiving the distribution amount
        db_record (obj) - model instance that triggered the distribution
        timestamp (str) - timestamp when the triggering event was received

    Attributes:
        distribution (obj) - (same as above)
        recipient (obj) - (same as above)
        proof (json) - JSON formatted object including the db_record and
            timestamp
        proof_item (obj) - (same as db_record above)

    """

    def __init__(
        self, distribution, recipient, db_record, timestamp, giver=None, hubs=None
    ):
        self.distribution = distribution
        self.recipient = recipient
        self.proof = self.generate_proof(db_record, timestamp)
        self.proof_item = db_record
        self.giver = giver
        self.hubs = hubs

    @staticmethod
    def generate_proof(db_record, timestamp):
        if db_record:
            serializer = get_model_serializer(type(db_record))
            obj = serializer(db_record).data
            if obj.get("password"):
                del obj["password"]
            proof = {
                "timestamp": timestamp,
                "table": db_record._meta.db_table,
                "record": obj,
            }
            return proof
        return None

    def reputation(self):
        if not self.giver or self.giver.reputation > 110:
            # If there is no giver, return the rep amount
            return self.distribution.reputation
        else:
            return 0

    def distribute(self):
        record = self._record_distribution()

        try:
            record.set_distributed_pending()
            self._update_reputation_and_balance(record)
            record.set_distributed()
        except Exception as e:
            record.set_distributed_failed()

            error_message = f"Distribution {record.id} failed"
            error = ReputationDistributorError(e, error_message)
            sentry.log_error(error)
            print(error_message, e)
        return record

    def _record_distribution(self):
        record = Distribution.objects.create(
            recipient=self.recipient,
            giver=self.giver,
            amount=self.distribution.amount,
            reputation_amount=self.reputation(),
            distribution_type=self.distribution.name,
            proof=self.proof,
            proof_item_content_type=(
                get_content_type_for_model(self.proof_item) if self.proof_item else None
            ),
            proof_item_object_id=self.proof_item.id if self.proof_item else None,
        )

        if self.hubs:
            record.hubs.add(*self.hubs)
        return record

    def _update_reputation_and_balance(self, record):
        # Prevents simultaneous changes to the user
        users = User.objects.filter(pk=self.recipient.id).select_for_update(
            of=("self",)
        )

        with transaction.atomic():
            rep = self.reputation()
            if self.distribution.gives_rep and rep:
                # updates at the SQL level and does not call save() or emit signals
                users.update(reputation=models.F("reputation") + rep)
            self._record_balance(record)

    def _record_balance(self, distribution):
        content_type = ContentType.objects.get_for_model(distribution)
        Balance.objects.create(
            user=self.recipient,
            content_type=content_type,
            object_id=distribution.id,
            amount=self.distribution.amount,  # db converts integer to string
        )
