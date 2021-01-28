import numpy as np
import time

from django.db import transaction, models
from django.db.models import FloatField, Func, Q, Count
from django.db.models.functions import Cast
from django.db.models.aggregates import Sum
from django.contrib.admin.options import get_content_type_for_model
from django.contrib.contenttypes.models import ContentType

from reputation.exceptions import ReputationDistributorError
from reputation.models import Distribution, Contribution
from reputation.distributions import Distribution as dist
from reputation.serializers import get_model_serializer
from purchase.models import Balance
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
    def __init__(
        self,
        distribution,
        recipient,
        db_record,
        timestamp,
        hubs=None
    ):
        self.distribution = distribution
        self.recipient = recipient
        self.proof = self.generate_proof(db_record, timestamp)
        self.proof_item = db_record
        self.hubs = hubs

    @staticmethod
    def generate_proof(db_record, timestamp):
        if db_record:
            serializer  = get_model_serializer(type(db_record))
            obj = serializer(db_record).data
            if obj.get('password'):
                del obj['password']
            proof = {
                'timestamp': timestamp,
                'table': db_record._meta.db_table,
                'record': obj
            }
            return proof
        return None

    def distribute(self):
        record = self._record_distribution()
        try:
            record.set_distributed_pending()
            self._update_reputation_and_balance(record)
            record.set_distributed()
        except Exception as e:
            record.set_distributed_failed()

            error_message = f'Distribution {record.id} failed'
            error = ReputationDistributorError(e, error_message)
            sentry.log_error(error)
            print(error_message, e)
        return record

    def _record_distribution(self):
        record = Distribution.objects.create(
            recipient=self.recipient,
            amount=self.distribution.amount,
            distribution_type=self.distribution.name,
            proof=self.proof,
            proof_item_content_type=get_content_type_for_model(
                self.proof_item
            ) if self.proof_item else None,
            proof_item_object_id=self.proof_item.id if self.proof_item else None
        )

        if self.hubs:
            record.hubs.add(*self.hubs)
        return record

    def _update_reputation_and_balance(self, record):
        # Prevents simultaneous changes to the user
        users = User.objects.filter(pk=self.recipient.id).select_for_update(
            of=('self',)
        )

        with transaction.atomic():
            if self.distribution.gives_rep:
                # updates at the SQL level and does not call save() or emit signals
                users.update(
                    reputation=models.F('reputation') + self.distribution.amount
                )
            self._record_balance(record)

    def _record_balance(self, distribution):
        content_type = ContentType.objects.get_for_model(distribution)
        Balance.objects.create(
            user=self.recipient,
            content_type=content_type,
            object_id=distribution.id,
            amount=self.distribution.amount  # db converts integer to string
        )


class RewardDistributor:
    prob_keys = (
        'SUBMITTER',
        'AUTHOR',
        'UPVOTER'
        'CURATOR',
        'COMMENTER',
    )
    prob_by_key = {
        'SUBMITTER': 0.1,
        'UPVOTER': 0.2,
        'AUTHOR': 0.4,
        'CURATOR': 0.15,
        'COMMENTER': 0.15
    }

    def get_papers_prob_dist(self, items):
        papers = items.order_by('id')
        weekly_total_score = papers.aggregate(
            total_sum=Sum('score') + Count('threads__votes', filter=Q(threads__votes__vote_type=1, threads__is_removed=False))
        )['total_sum']
        prob_dist = papers.annotate(
            p=Cast(
                Func(
                    Sum('score') + Count('threads__votes', filter=Q(threads__votes__vote_type=1, threads__is_removed=False)),
                    function='ABS'
                )/float(weekly_total_score),
                FloatField()
            )
        ).values_list(
            'p',
            flat=True
        )
        return papers, np.array(prob_dist)

    def get_random_item(self, items, p=None):
        # Uniform distribution if p is none
        item = np.random.choice(items, p=p)
        return item

    def generate_distribution(self, item, amount=1, distribute=True):
        from paper.models import Paper, Vote
        from user.models import User, Author
        from bullet_point.models import BulletPoint, Vote as BulletPointVote
        from summary.models import Summary, Vote as SummaryVote
        from discussion.models import Thread, Comment, Reply

        item_type = type(item)

        if item_type is Contribution:
            content_type = item.content_type
            try:
                item = content_type.get_object_for_this_type(id=item.object_id)
                item_type = type(item)
            except Exception as e:
                print(e)
                return None

        if item_type is Paper:
            recipient = item.uploaded_by
        elif item_type is BulletPoint:
            recipient = item.created_by
        elif item_type is BulletPointVote:
            recipient = item.created_by
        elif item_type is Summary:
            recipient = item.proposed_by
        elif item_type is SummaryVote:
            recipient = item.created_by
        elif item_type is Vote:
            recipient = item.created_by
        elif item_type is User:
            recipient = item
        elif item_type is Author:
            recipient = item.user
        elif item_type in (Thread, Comment, Reply):
            recipient = item.created_by
        else:
            error = Exception(f'Missing instance type: {str(item_type)}')
            sentry.log_error(error)
            raise error

        distributor = Distributor(
            dist('REWARD', amount, False),
            recipient,
            item,
            time.time()
        )

        if distribute:
            distribution = distributor.distribute()
        else:
            distribution = distributor

        return distribution
