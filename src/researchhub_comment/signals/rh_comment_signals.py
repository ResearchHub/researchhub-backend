from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Vote, dispatch_uid='update_citation_vote_score')
def from_legacy_to_rh_comment():