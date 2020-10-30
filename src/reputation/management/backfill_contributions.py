'''
Creates a wallet for users
'''

import datetime

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from reputation.models import DistributionAmount, Contribution
from user.models import Action


class Command(BaseCommand):

    def handle(self, *args, **options):
        paper_content = ContentType.objects.get(
            app_label='paper',
            model='paper'
        )
        paper_vote_content = ContentType.objects.get(
            app_label='paper',
            model='vote'
        )
        thread_content = ContentType.objects.get(
            app_label='discussion',
            model='thread'
        )
        comment_content = ContentType.objects.get(
            app_label='discussion',
            model='comment'
        )
        reply_content = ContentType.objects.get(
            app_label='discussion',
            model='reply'
        )
        bullet_content = ContentType.objects.get(
            app_label='bullet_point',
            model='bulletpoint'
        )
        contribution_content_types = (
            paper_content,
            paper_vote_content,
            thread_content,
            comment_content,
            reply_content,
            bullet_content
        )

        first_distribution_date = datetime.datetime(
            year=2020,
            month=10,
            day=29,
            hour=0,
            minute=0
        )

        last_dist = DistributionAmount.objects.last()
        if not last_dist:
            dist = DistributionAmount.objects.create(
                distributed=True,
                amount=1000000
            )
            dist.distributed_date = first_distribution_date
            dist.save()

        actions = Action.objects.filter(
            created_date__gte=first_distribution_date
        )
        for action in actions.iterator():
            content_type = action.content_type
            obj_id = action.obj_id
            if content_type in contribution_content_types:
                if content_type is paper_content:
                    choice = Contribution.SUBMITTER
                    paper = content_type.model_class().objects.get(id=obj_id)
                elif content_type is paper_vote_content:
                    choice = Contribution.UPVOTER
                elif content_type is thread_content:
                    choice = Contribution.COMMENTER
                elif content_type is comment_content:
                    choice = Contribution.COMMENTER
                elif content_type is reply_content:
                    choice = Contribution.COMMENTER
                elif content_type is bullet_content:
                    choice = Contribution.CURATOR

                paper = content_type.model_class().objects.get(
                    id=obj_id
                ).paper

                Contribution.objects.create(
                    contribution_type=choice,
                    user=action.user,
                    content_type=content_type,
                    object_id=obj_id,
                    paper=paper
                )
