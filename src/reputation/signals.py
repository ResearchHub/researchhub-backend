from time import time

from django.contrib.admin.options import get_content_type_for_model
from django.db.models.signals import m2m_changed, post_delete
from django.dispatch import receiver

import reputation.distributions as distributions
from paper.models import Paper
from reputation.distributor import Distributor
from reputation.models import Distribution
from researchhub_document.models import ResearchhubUnifiedDocument

NEW_USER_BONUS_REPUTATION_LIMIT = 200
NEW_USER_BONUS_DAYS_LIMIT = 30


@receiver(
    m2m_changed,
    sender=ResearchhubUnifiedDocument.hubs.through,
    dispatch_uid="unified_doc_hubs_changed",
)
def update_distribution_for_hub_changes(
    sender, instance, action, reverse, model, pk_set, **kwargs
):
    if (
        (action == "post_add")
        and pk_set is not None
        and instance.document_type == "PAPER"
    ):
        distributions = Distribution.objects.filter(
            proof_item_object_id=instance.paper.id,
            proof_item_content_type=get_content_type_for_model(instance.paper),
        )
        for distribution in distributions:
            distribution.hubs.add(*instance.hubs.all())


@receiver(post_delete, sender=Paper, dispatch_uid="censor_paper")
def distribute_for_censor_paper(sender, instance, using, **kwargs):
    timestamp = time()
    flags = instance.flags.select_related("created_by").all()
    for flag in flags:
        recipient = flag.created_by
        if is_eligible_user(recipient):
            distributor = Distributor(
                distributions.FlagPaper,
                recipient,
                instance,
                timestamp,
                instance.created_by,
                instance.hubs.all(),
            )
            distributor.distribute()


def is_eligible_user(user):
    if user is not None:
        return user.is_active and not user.is_suspended
    return False


@receiver(post_delete, sender=Distribution, dispatch_uid="delete_distribution")
def revoke_reputation(sender, instance, **kwargs):
    # TODO: Use F expression here to avoid race conditions
    recipient = instance.recipient
    amount = instance.amount
    current = recipient.reputation
    recipient.reputation = current - amount
    recipient.save(update_fields=["reputation"])
