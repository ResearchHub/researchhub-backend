from .models import Distribution


class Distributor:
    '''
    Distributes an amount to the request user's reputation and logs this event
    by creating an Distribution record in the database.
    '''
    def __init__(self, distribution, request, sender):
        self.distribution = distribution
        self.recipient = request.user
        self.sender = sender

    @staticmethod
    def generate_proof(sender):
        # TODO
        return sender

    def distribute(self):
        self.proof = self.generate_proof(self.sender)
        self._create_issuance()
        self._update_reputation()

        print("Distribution complete")

    def _create_issuance(self):
        Distribution.objects.create(
            recipient=self.recipient,
            distribution_amount=self.distribution.amount,
            distribution_name=self.distribution.name,
            proof=self.proof
        )

        print("Issuance created")

    def _update_reputation(self):
        current = self.recipient.reputation
        self.recipient.reputation = current + self.distribution.amount
        self.recipient.save(update_fields=['reputation'])

        print("Reputation updated")
