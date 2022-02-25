from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify
from django.utils.crypto import get_random_string
from discussion.reaction_models import Vote

from hypothesis.models import Hypothesis
from reputation.models import Contribution
from reputation.tasks import create_contribution


@receiver(post_save, sender=Hypothesis, dispatch_uid='add_hypothesis_slug')
def add_hypothesis_slug(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if created:
        suffix = get_random_string(length=32)
        slug = slugify(instance.title)
        if not slug:
            slug += suffix
        instance.slug = slug
        instance.save()


@receiver(
    post_save,
    sender=Hypothesis,
    dispatch_uid='hypothesis_upvote_on_create',
)
def hypothesis_upvote_on_create(
    created,
    instance,
    **kwargs
):
    if (created):
        vote = Vote.objects.create(
          item=instance,
          created_by=instance.created_by,
          vote_type=Vote.UPVOTE
        )
        vote.save()


@receiver(
    post_save,
    sender=Hypothesis,
    dispatch_uid='hypothesis_create_contribution',
)
def hypothesis_create_contribution(
    created,
    instance,
    sender,
    update_fields,
    **kwargs
):
    if created:
        created_by = instance.created_by
        unified_doc_id = instance.unified_document.id
        create_contribution.apply_async(
            (
                Contribution.SUBMITTER,
                {
                    'app_label': 'hypothesis',
                    'model': 'hypothesis'
                },
                created_by.id,
                unified_doc_id,
                instance.id
            ),
            priority=3,
            countdown=5
        )
