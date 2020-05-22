'''
Set all distribution statuses to so they are eligible for withdrawal.
'''
from django.core.management.base import BaseCommand

from reputation.models import Distribution

from bullet_point.models import (
    BulletPoint,
    Endorsement as BulletPointEndorsement,
    Flag as BulletPointFlag
)
from discussion.models import (
    Comment,
    Endorsement as DiscussionEndorsement,
    Flag as DiscussionFlag,
    Reply,
    Thread,
    Vote as DiscussionVote
)
from paper.models import (
    Flag as PaperFlag,
    Paper,
    Vote as PaperVote
)

class Command(BaseCommand):

    def handle(self, *args, **options):
        distributions = Distribution.objects.all()
        count = distributions.count()
        for i, distribution in enumerate(distributions):
            print('{} / {}'.format(i, count))
            instance = distribution.proof_item
            hubs = None
            if isinstance(instance, BulletPoint) and instance.paper:
                hubs = instance.paper.hubs
            elif isinstance(instance, Comment):
                hubs = instance.parent.paper.hubs
            elif isinstance(instance, Reply):
                try:
                    hubs = instance.parent.parent.paper.hubs
                except Exception as e:
                    print(e)
            elif isinstance(instance, Thread) and instance.paper:
                hubs = instance.paper.hubs
            elif isinstance(instance, PaperVote) and instance.paper:
                hubs = instance.paper.hubs

            if isinstance(instance, Paper):
                hubs = instance.hubs

            if isinstance(instance, BulletPointFlag):
                hubs = instance.bullet_point.paper.hubs

            elif isinstance(instance, BulletPointEndorsement):
                hubs = instance.bullet_point.paper.hubs

            if isinstance(instance, DiscussionFlag):
                if isinstance(instance.item, BulletPoint):
                    hubs = instance.item.paper.hubs
                elif isinstance(instance.item, Comment):
                    hubs = instance.item.parent.paper.hubs
                elif isinstance(instance.item, Reply):
                    try:
                        hubs = instance.item.parent.parent.paper.hubs
                    except Exception as e:
                        print(e)
                elif isinstance(instance.item, Thread):
                    hubs = instance.item.paper.hubs

            elif isinstance(instance, DiscussionEndorsement):
                recipient = instance.item.created_by

                if isinstance(instance.item, BulletPoint):
                    hubs = instance.item.paper.hubs
                elif isinstance(instance.item, Comment):
                    hubs = instance.item.parent.paper.hubs
                elif isinstance(instance.item, Reply):
                    try:
                        hubs = instance.item.parent.parent.paper.hubs
                    except Exception as e:
                        sentry.log_error(e)
                elif isinstance(instance.item, Thread):
                    hubs = instance.item.paper.hubs

            if hubs:
                distribution.hubs.add(*hubs.all())
