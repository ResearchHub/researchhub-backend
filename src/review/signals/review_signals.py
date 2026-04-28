from django.db.models.signals import post_save
from django.dispatch import receiver

from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from user.models import User


@receiver(post_save, sender=Purchase, dispatch_uid="review_assessed_on_purchase")
def mark_review_assessed_on_purchase(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.content_type.model != "rhcommentmodel":
        return
    if not User.is_rh_community_account(instance.user):
        return
    comment = instance.item
    if comment is None:
        return
    comment.reviews.filter(is_assessed=False).update(is_assessed=True)


@receiver(
    post_save, sender=BountySolution, dispatch_uid="review_assessed_on_bounty_award"
)
def mark_review_assessed_on_bounty_award(sender, instance, **kwargs):
    if instance.status != BountySolution.Status.AWARDED:
        return
    if instance.content_type.model != "rhcommentmodel":
        return
    if not User.is_rh_community_account(instance.bounty.created_by):
        return
    comment = instance.item
    if comment is None:
        return
    comment.reviews.filter(is_assessed=False).update(is_assessed=True)
