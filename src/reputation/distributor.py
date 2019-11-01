from .models import Distribution
from .serializers import get_model_serializer

# TODO: Add logging flag


class Distributor:
    '''
    Distributes an amount to the request user's reputation and logs this event
    by creating an Distribution record in the database.
    '''
    def __init__(self, distribution, recipient, db_record, timestamp):
        self.distribution = distribution
        self.recipient = recipient
        self.proof = self.generate_proof(db_record, timestamp)

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
        try:
            self._record_distribution()
            self._update_reputation()
            # print('Distribution complete')
        except Exception as e:
            print('Distribution failed', e)

    def _record_distribution(self):
        record = Distribution.objects.create(
            recipient=self.recipient,
            amount=self.distribution.amount,
            distribution_type=self.distribution.name,
            proof=self.proof
        )

        # print('Distribution created:', str(record))

    # TODO: Queue this so that there is no race condition
    def _update_reputation(self):
        user = self.recipient
        current = user.reputation
        user.reputation = current + self.distribution.amount
        user.save(update_fields=['reputation'])

        # print(f'Reputation updated for user {user}:', str(user.reputation))
