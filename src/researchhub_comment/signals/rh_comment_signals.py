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
from researchhub_comment.constants.rh_comment_migration_legacy_types import LEGACY_COMMENT, LEGACY_REPLY, LEGACY_THREAD
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.models import RhCommentThreadModel, RhCommentModel
from utils import sentry


@receiver(post_save, sender=LegacyThread, dispatch_uid='from_legacy_thread_to_rh_comment')
def from_legacy_thread_to_rh_comment(sender, instance, created, **kwargs):
    try:
        belonging_document = get_belonging_doc(instance)
        belonging_thread = find_or_create_belonging_thread(belonging_document)
        legacy_thread_id = instance.id
        upserter = instance.created_by

        RhCommentModel(
            comment_content_src=ContentFile((instance.plain_text or "").encode()),
            comment_content_type=QUILL_EDITOR,
            created_by=upserter,
            created_date=instance.created_date,
            legacy_id=legacy_thread_id,
            legacy_model_type=LEGACY_THREAD,
            thread=belonging_thread,
            updated_by=upserter,
        ).save()

        # intentionally querying DB to ensure that the instance was created properly 
        return RhCommentModel.objects.get(        
            legaacy_id=legacy_thread_id,
            legacy_model_type=LEGACY_THREAD,
        )
        
    except Exception as error:
        sentry.log_error('rh_comment_signals: ', error)

@receiver(post_save, sender=LegacyComment, dispatch_uid='from_legacy_comment_to_rh_comment')
def from_legacy_comment_to_rh_comment(sender, instance, created, **kwargs):
    try:
        belonging_document = get_belonging_doc(instance)
        belonging_thread = find_or_create_belonging_thread(belonging_document)
        legacy_comment_id = instance.id
        legacy_thread = instance.parent  # Legacy Comment HAS to have a legacy Thread as a parent
        upserter = instance.created_by

        migrated_comment = RhCommentModel.objects.filter(
            legaacy_id=legacy_comment_id,
            legacy_model_type=LEGACY_COMMENT,
        ).first()

        if migrated_comment is not None:
            migrated_comment.comment_content_src = ContentFile((instance.plain_text or "").encode())
            migrated_comment.save()
        else:
            # Logical ordering. Do not change unless you know what you're doing.
            migrated_comment_prep = RhCommentModel(
                comment_content_src=ContentFile((instance.plain_text or "").encode()),
                comment_content_type=QUILL_EDITOR,  # currently FE utilizes only Quill for
                created_by=upserter,
                created_date=instance.created_date,
                legacy_id=legacy_comment_id,
                legacy_model_type=LEGACY_COMMENT,
                thread=belonging_thread,
                updated_by=upserter,
            )

            # BUUBLE UP: Legacy thread was a type of commenting module. It was NOT meerely a grouping tool.
            migrated_legacy_thread_comment = RhCommentModel.objects.filter(
                legacy_id=legacy_thread.id,
                legacy_model_type=LEGACY_THREAD,
            ).first() or from_legacy_thread_to_rh_comment(
                sender, legacy_thread, created, **kwargs
            )
            migrated_comment_prep.parent = migrated_legacy_thread_comment
            migrated_comment_prep.save()

        # intentionally querying DB to ensure that the instance was created properly 
        return RhCommentModel.objects.get(
            legaacy_id=legacy_comment_id,
            legacy_model_type=LEGACY_COMMENT,
        )

    except Exception as error:
        sentry.log_error('rh_comment_signals: ', error)

@receiver(post_save, sender=LegacyReply, dispatch_uid='from_legacy_reply_to_rh_comment')
def from_legacy_reply_to_rh_comment(sender, instance, created, **kwargs):
    try:
        belonging_document = get_belonging_doc(instance)
        belonging_thread = find_or_create_belonging_thread(belonging_document)
        # Legacy Reply HAS to have a parent. In unique cases,this could be another reply...
        legacy_comment = instance.parent
        legacy_reply_id = instance.id
        upserter = instance.created_by

        migrated_reply = RhCommentModel.objects.filter(
            legaacy_id=legacy_reply_id,
            legacy_model_type=LEGACY_REPLY,
        ).first()

        if migrated_reply is not None:
            migrated_reply.comment_content_src = ContentFile((instance.plain_text or "").encode())
            migrated_reply.save()
        else:
            # Logical ordering. Do not change unless you know what you're doing.
            migrated_reply_prep = RhCommentModel(
                comment_content_src=ContentFile((instance.plain_text or "").encode()),
                comment_content_type=QUILL_EDITOR,  # currently FE utilizes only Quill for
                created_by=upserter,
                created_date=instance.created_date,
                legacy_id=legacy_reply_id,
                legacy_model_type=LEGACY_REPLY,
                thread=belonging_thread,
                updated_by=upserter,
            )

            # BUUBLE UP
            migrated_legacy_comment = RhCommentModel.objects.filter(
                legacy_id=legacy_comment.id,
                legacy_model_type=LEGACY_COMMENT,
            ).first() or from_legacy_comment_to_rh_comment(
                sender, legacy_comment, created, **kwargs
            )
            migrated_reply_prep.parent = migrated_legacy_comment
            migrated_reply_prep.save()

        return RhCommentModel.objects.get(
            legaacy_id=legacy_reply_id,
            legacy_model_type=LEGACY_REPLY,
        )

    except Exception as error:
        sentry.log_error('rh_comment_signals: ', error)

def get_belonging_doc(instance):
    # currently migration supported documents
    return instance.paper or instance.post or instance.hypothesis or instance.citation

def find_or_create_belonging_thread(belonging_document):
    return RhCommentThreadModel.objects.filter(
        content_type=ContentType.objects.get_for_model(belonging_document),
        object_id=belonging_document.id,
        thread_type=GENERIC_COMMENT,  # currently only backfilling generic comments
    ).first() or RhCommentThreadModel.objects.create(
        content_type=ContentType.objects.get_for_model(belonging_document),
        object_id=belonging_document.id,
        thread_type=GENERIC_COMMENT,  # currently only backfilling generic comments
    )
