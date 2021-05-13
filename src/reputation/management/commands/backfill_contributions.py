'''
Creates a wallet for users
'''

import datetime

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from reputation.models import DistributionAmount, Contribution
from reputation.tasks import create_contribution
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
            minute=0,
            second=0
        )

        last_dist = DistributionAmount.objects.last()
        if not last_dist:
            dist = DistributionAmount.objects.create(
                distributed=False,
                amount=1000000
            )
            DistributionAmount.objects.filter(
                id=dist.id
            ).update(
                created_date=first_distribution_date,
                distributed_date=first_distribution_date
            )

        actions = Action.objects.filter(
            created_date__gte=first_distribution_date
        )
        for action in actions.iterator():
            content_type = action.content_type
            user = action.user
            obj_id = action.object_id
            if content_type in contribution_content_types:
                if content_type == paper_content:
                    choice = Contribution.SUBMITTER
                    instance_type = {
                        'app_label': 'paper',
                        'model': 'paper'
                    }
                elif content_type == paper_vote_content:
                    choice = Contribution.UPVOTER
                    instance_type = {
                        'app_label': 'paper',
                        'model': 'vote'
                    }
                elif content_type == thread_content:
                    choice = Contribution.COMMENTER
                    instance_type = {
                        'app_label': 'discussion',
                        'model': 'thread'
                    }
                elif content_type == comment_content:
                    choice = Contribution.COMMENTER
                    instance_type = {
                        'app_label': 'discussion',
                        'model': 'comment'
                    }
                elif content_type == reply_content:
                    choice = Contribution.COMMENTER
                    instance_type = {
                        'app_label': 'discussion',
                        'model': 'reply'
                    }
                elif content_type == bullet_content:
                    choice = Contribution.CURATOR
                    instance_type = {
                        'app_label': 'bullet_point',
                        'model': 'bulletpoint'
                    }

                try:
                    if content_type == paper_content:
                        paper = content_type.model_class().objects.get(
                            id=obj_id
                        )
                    else:
                        paper = content_type.model_class().objects.get(
                            id=obj_id
                        ).paper

                    create_contribution(
                        choice,
                        instance_type,
                        user.id,
                        paper.id,
                        obj_id
                    )
                except Exception as e:
                    # Don't create contributions if there is an error
                    # such as a paper no longer exists
                    print(e)
