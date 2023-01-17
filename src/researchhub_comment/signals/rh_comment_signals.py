from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.models import (
    Comment as LegacyComment,
    Reply as LegacyReply,
    Thread as LegacyThread,
)
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.constants.rh_comment_migration_legacy_types import LEGACY_COMMENT, LEGACY_THREAD
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.models import RhCommentThreadModel, RhCommentModel

@receiver(post_save, sender=LegacyComment, dispatch_uid='from_legacy_comment_to_rh_comment')
def from_legacy_comment_to_rh_comment(sender, instance, created, **kwargs):
    try:
        beloging_document = get_comment_belonging_doc(instance)
        comment_creator = instance.created_by
        legacy_comment_id = instance.id
        
        belonging_thread = RhCommentThreadModel.objects.filter(
            content_type=ContentType.objects.get_for_model(beloging_document),
            object_id=beloging_document.id,
            thread_type=GENERIC_COMMENT,  # currently only backfilling generic comment
        ).first() or RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(beloging_document),
            object_id=beloging_document.id,
            thread_type=GENERIC_COMMENT,  # currently only backfilling generic comment
        )
        
        migrated_comment = RhCommentModel.objects.filter(
            legaacy_id=legacy_comment_id,
            legacy_model_type=LEGACY_COMMENT,
        ).first()

        if migrated_comment is None:
            migrated_comment_shell = RhCommentModel(
                comment_content_src=ContentFile((instance.plain_text or "").encode()),
                comment_content_type=QUILL_EDITOR,
                created_by=comment_creator,
                created_date=instance.created_date,
                legacy_id=legacy_comment_id,
                legacy_model_type=LEGACY_COMMENT,
                thread=belonging_thread,
                updated_by=comment_creator,
            )
        else:
            migrated_comment.comment_content_src = ContentFile((instance.plain_text or "").encode())
            migrated_comment.save()
        
        # legacy thread was a type of commenting module. It was NOT meerely a grouping tool.
        legacy_thread = instance.parent
        # if migrated_comment
        # migrated_legacy_thread = RhCommentModel.objects.filter(
        #     legacy_id=legacy_comment_id,
        #     legacy_model_type=LEGACY_THREAD,
        # ).first() if legacy_thread is not None else None
        
    except Exception as error:
            #  implement


@receiver(post_save, sender=LegacyReply, dispatch_uid='from_legacy_reply_to_rh_comment')
def from_legacy_reply_to_rh_comment(sender, instance, created, **kwargs):
    RhCommentThreadModel
    #  implement


@receiver(post_save, sender=LegacyThread, dispatch_uid='from_legacy_thread_to_rh_comment')
def from_legacy_thread_to_rh_comment(sender, instance, created, **kwargs):
    RhCommentThreadModel
    #  implement

def get_comment_belonging_doc(instance):
    return instance.paper or instance.post or instance.hypothesis or instance.citation



