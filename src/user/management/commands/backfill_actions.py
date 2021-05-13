from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from user.models import Action
from paper.models import Vote as PaperVote
from discussion.models import Vote as DisVote


class Command(BaseCommand):

    def handle(self, *args, **options):
        paper_votes = PaperVote.objects.all()
        paper_votes_count = paper_votes.count()
        paper_vote_content = ContentType.objects.get(
            app_label='paper',
            model='vote'
        )
        for i, paper_vote in enumerate(paper_votes):
            print(f'{i}/{paper_votes_count}')
            action, created = Action.objects.get_or_create(
                user=paper_vote.created_by,
                content_type_id=paper_vote_content.id,
                object_id=paper_vote.id,
                display=False,
            )

            if created:
                action.created_date = paper_vote.created_date
                action.updated_date = paper_vote.updated_date
                action.save()

        discussion_votes = DisVote.objects.all()
        discussion_votes_count = discussion_votes.count()
        dis_vote_content = ContentType.objects.get(
            app_label='discussion',
            model='vote'
        )
        for i, dis_vote in enumerate(discussion_votes):
            print(f'{i}/{discussion_votes_count}')
            action, created = Action.objects.get_or_create(
                user=dis_vote.created_by,
                content_type_id=dis_vote_content.id,
                object_id=dis_vote.id,
                display=False
            )

            if created:
                action.created_date = paper_vote.created_date
                action.updated_date = paper_vote.updated_date
                action.save()
