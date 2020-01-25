from django.core.management.base import BaseCommand
from user.models import Action
from reputation.models import Distribution
from discussion.models import Comment, Thread, Reply
from summary.models import Summary
from paper.models import Vote as PaperVote

class Command(BaseCommand):

    def handle(self, *args, **options):
        distribution = Distribution.objects.all()
        comments = Comment.objects.all()
        for comment in comments:
            action, created = Action.objects.get_or_create(
                user=comment.created_by,
                content_type_id=13,
                object_id=comment.id,
            )

            action.created_date = comment.created_date
            action.updated_date = comment.updated_date

            if created:
                action.hubs.add(*comment.parent.paper.hubs.all())
            
            action.save()
        
        threads = Thread.objects.all()
        for thread in threads:
            action, created = Action.objects.get_or_create(
                user=thread.created_by,
                content_type_id=15,
                object_id=thread.id,
            )

            action.created_date = thread.created_date
            action.updated_date = thread.updated_date

            if created:
                action.hubs.add(*thread.paper.hubs.all())
            
            action.save()

        summaries = Summary.objects.all()
        for summary in summaries:
            action, created = Action.objects.get_or_create(
                user=summary.proposed_by,
                content_type_id=25,
                object_id=summary.id,
            )

            action.created_date = summary.created_date
            action.updated_date = summary.updated_date

            if created:
                action.hubs.add(*summary.paper.hubs.all())
            
            action.save()
        
        paper_votes = PaperVote.objects.all()
        for vote in paper_votes:
            action, created = Action.objects.get_or_create(
                user=vote.created_by,
                content_type_id=20,
                object_id=vote.id,
            )

            action.created_date = vote.created_date
            action.updated_date = vote.updated_date

            if created:
                action.hubs.add(*vote.paper.hubs.all())
            
            action.save()
        
        # replies = Reply.objects.all()
        # for reply in replies:
        #     action, created = Action.objects.get_or_create(
        #         user=reply.created_by,
        #         content_type_id=15,
        #         object_id=reply.id,
        #     )

        #     action.created_date = reply.created_date
        #     action.updated_date = reply.updated_date

        #     if created:
        #         action.hubs.add(*reply.parent.paper.hubs.all())
            
        #     action.save()

        # for dist in distribution:
        #     action = Action.objects.create(
        #         user=comment.recipient,
        #         content_type=dist.proof_item_content_type,
        #         object_id=dist.proof_item,
        #     )
        #     if content_type == 'VOTE_ON_PAPER'
        #     action.hubs.add()
