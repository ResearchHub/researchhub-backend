from .models import Distribution


class Distributor:
    '''
    Distributes an amount to the request user's reputation and logs this event
    by creating an Distribution record in the database.
    '''
    def __init__(self, distribution, recipient, db_record):
        self.distribution = distribution
        self.recipient = recipient
        self.proof = self.generate_proof(db_record)

    @staticmethod
    def generate_proof(db_record):
        # TODO
        return str(db_record)

    def distribute(self):
        self._record_distribution()
        self._update_reputation()

        print("Distribution complete")

    def _record_distribution(self):
        record = Distribution.objects.create(
            recipient=self.recipient,
            amount=self.distribution.amount,
            distribution_type=self.distribution.name,
            proof=self.proof
        )

        print("Distribution created:", str(record))

    def _update_reputation(self):
        user = self.recipient
        current = user.reputation
        user.reputation = current + self.distribution.amount
        user.save(update_fields=['reputation'])

        print("Reputation updated:", str(user))
