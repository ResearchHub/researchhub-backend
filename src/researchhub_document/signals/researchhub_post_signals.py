from django.db.models.signals import post_save
from django.dispatch import receiver

from researchhub_document.models import ResearchhubPost
from discussion.reaction_models import Vote


@receiver(
    post_save,
    sender=ResearchhubPost,
    dispatch_uid='rh_post_add_upvote_by_creator_on_create',
)
def rh_post_add_upvote_by_creator_on_create(
    created,
    instance,
    sender,
    update_fields,
    **kwargs
):
    if (created):
        vote = Vote.objects.create(
          item=instance,
          created_by=instance.created_by,
          vote_type=Vote.UPVOTE
        )
        vote.save()
