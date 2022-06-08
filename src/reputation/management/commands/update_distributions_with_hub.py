"""
Set all distribution statuses to so they are eligible for withdrawal.
"""
from django.core.management.base import BaseCommand

from bullet_point.models import BulletPoint
from bullet_point.models import Endorsement as BulletPointEndorsement
from bullet_point.models import Flag as BulletPointFlag
from discussion.models import Comment
from discussion.models import Endorsement as DiscussionEndorsement
from discussion.models import Flag as DiscussionFlag
from discussion.models import Reply, Thread
from discussion.models import Vote as GrmVote
from paper.models import Paper
from reputation.models import Distribution


class Command(BaseCommand):
    def handle(self, *args, **options):
        distributions = Distribution.objects.all()
        count = distributions.count()
        for i, distribution in enumerate(distributions):
            print("{} / {}".format(i, count))
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
            elif isinstance(instance, GrmVote) and instance.paper:
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
