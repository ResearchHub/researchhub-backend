from django.db import transaction
from django.contrib.admin.options import get_content_type_for_model

from reputation.exceptions import ReputationDistributorError
from reputation.models import Distribution
from reputation.serializers import get_model_serializer
from user.models import User
import utils.sentry as sentry


class Distributor:
    '''
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

    '''
    def __init__(self, distribution, recipient, db_record, timestamp):
        self.distribution = distribution
        self.recipient = recipient
        self.proof = self.generate_proof(db_record, timestamp)
        self.proof_item = db_record

    @staticmethod
    def generate_proof(db_record, timestamp):
        serializer = get_model_serializer(type(db_record))
        proof = {
            'timestamp': timestamp,
            'table': db_record._meta.db_table,
            'record': serializer(db_record).data
        }
        return proof

    def distribute(self):
        record = self._record_distribution()
        try:
            record.set_distributed_pending()
            self._update_reputation()
            record.set_distributed()
        except Exception as e:
            record.set_distributed_failed()

            error_message = f'Distribution {record.id} failed'
            error = ReputationDistributorError(e, error_message)
            sentry.log_error(error)
            print(error_message, e)
        return record

    def _record_distribution(self):
        print(self.proof_item)
        record = Distribution.objects.create(
            recipient=self.recipient,
            amount=self.distribution.amount,
            distribution_type=self.distribution.name,
            proof=self.proof,
            proof_item_content_type=get_content_type_for_model(
                self.proof_item
            ),
            proof_item_object_id=self.proof_item.id
        )
        return record

    def _update_reputation(self):
        users = User.objects.filter(pk=self.recipient.id).select_for_update(
            of=('self',)
        )

        with transaction.atomic():
            user = users.get()
            current = user.reputation
            user.reputation = current + self.distribution.amount
            user.save(update_fields=['reputation'])
