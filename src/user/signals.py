# TODO: Fix the celery task on cloud deploys

from django.db.models.signals import post_save
from django.dispatch import receiver
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider

from discussion.models import Comment, Reply, Thread, Vote as DiscussionVote
from mailing_list.tasks import notify_immediate
from paper.models import Paper, Vote as PaperVote
from researchhub.settings import TESTING
from summary.models import Summary
from user.models import Action, Author
from user.tasks import link_author_to_papers, link_paper_to_authors


@receiver(post_save, sender=Author, dispatch_uid='link_author_to_papers')
def queue_link_author_to_papers(sender, instance, created, **kwargs):
    """Runs a queued task to link the new ORCID author to existing papers."""
    if created:
        try:
            orcid_account = SocialAccount.objects.get(
                user=instance.user,
                provider=OrcidProvider.id
            )
            if not TESTING:
                link_author_to_papers.apply_async(
                    (instance.id, orcid_account.id)
                )
            else:
                link_author_to_papers(instance.id, orcid_account.id)
        except SocialAccount.DoesNotExist:
            pass


@receiver(post_save, sender=Paper, dispatch_uid='link_paper_to_authors')
def queue_link_paper_to_authors(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    """Runs a queued task linking ORCID authors to papers with updated dois."""
    if created or doi_updated(update_fields):
        if instance.doi is not None:
            try:
                if not TESTING:
                    link_paper_to_authors.apply_async(
                        (instance.id,)
                    )
                else:
                    link_paper_to_authors(instance.id)
            except SocialAccount.DoesNotExist:
                pass


def doi_updated(update_fields):
    if update_fields is not None:
        return 'doi' in update_fields
    return False


@receiver(post_save, sender=Summary, dispatch_uid='create_summary_action')
@receiver(post_save, sender=Comment, dispatch_uid='create_comment_action')
@receiver(post_save, sender=Reply, dispatch_uid='create_reply_action')
@receiver(post_save, sender=Thread, dispatch_uid='create_thread_action')
@receiver(
    post_save,
    sender=DiscussionVote,
    dispatch_uid='create_discussion_vote_action'
)
@receiver(post_save, sender=PaperVote, dispatch_uid='create_paper_vote_action')
def create_action(sender, instance, created, **kwargs):
    if created:
        if sender == Summary:
            user = instance.proposed_by
        else:
            user = instance.created_by

        action = Action.objects.create(
            item=instance,
            user=user
        )

        hubs = get_related_hubs(instance)
        action.hubs.add(*hubs)
        return action

def get_related_hubs(instance):
    paper = instance.paper
    return paper.hubs.all()

@receiver(post_save, sender=Action, dispatch_uid='send_action_notification')
def send_immediate_action_notification(sender, instance, created, **kwargs):
    if created:
        if instance:
            if not TESTING:
                notify_immediate.apply_async((instance.id,), priority=5)
            else:
                notify_immediate(instance.id)

