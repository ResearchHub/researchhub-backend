import json

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.models import Comment as LegacyComment
from discussion.models import Reply as LegacyReply
from discussion.models import Thread as LegacyThread
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.constants.rh_comment_migration_legacy_types import (
    LEGACY_COMMENT,
    LEGACY_REPLY,
    LEGACY_THREAD,
)
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from utils import sentry


@receiver(
    post_save, sender=LegacyThread, dispatch_uid="from_legacy_thread_to_rh_comment"
)
def from_legacy_thread_to_rh_comment(sender, instance, created, **kwargs):
    try:
        upserter = instance.created_by
        belonging_document = get_belonging_doc(instance)
        belonging_thread = find_or_create_belonging_thread(belonging_document, upserter)

        legacy_thread_id = instance.id
        migrated_thread_comment = RhCommentModel.objects.filter(
            legacy_id=legacy_thread_id,
            legacy_model_type=LEGACY_THREAD,
        ).first() or RhCommentModel.objects.create(
            comment_content_json=instance.text,
            comment_content_type=QUILL_EDITOR,
            context_title=instance.context_title,
            created_by=upserter,
            created_date=instance.created_date,
            legacy_id=legacy_thread_id,
            legacy_model_type=LEGACY_THREAD,
            thread=belonging_thread,
            updated_by=upserter,
        )
        comment_content_file = ContentFile(
            (json.dumps(instance.text) or instance.plain_text or "").encode()
        )
        migrated_thread_comment.comment_content_src.save(
            f"rh-comment-user-{upserter.id}-thread-{belonging_thread.id}-comment-{migrated_thread_comment.id}.txt",
            comment_content_file,
        )
        # intentionally querying DB to ensure that the instance was created properly
        return RhCommentModel.objects.get(
            legacy_id=legacy_thread_id,
            legacy_model_type=LEGACY_THREAD,
        )

    except Exception as error:
        sentry.log_error("from_legacy_thread_to_rh_comment: ", error)


@receiver(
    post_save, sender=LegacyComment, dispatch_uid="from_legacy_comment_to_rh_comment"
)
def from_legacy_comment_to_rh_comment(sender, instance, created, **kwargs):
    try:
        upserter = instance.created_by
        belonging_document = get_belonging_doc(instance)
        belonging_thread = find_or_create_belonging_thread(belonging_document, upserter)
        comment_content_file = ContentFile(
            (json.dumps(instance.text) or instance.plain_text or "").encode()
        )
        legacy_comment_id = instance.id
        legacy_thread = (
            instance.parent
        )  # Legacy Comment HAS to have a legacy Thread as a parent

        migrated_comment = RhCommentModel.objects.filter(
            legacy_id=legacy_comment_id,
            legacy_model_type=LEGACY_COMMENT,
        ).first()

        if migrated_comment is not None:
            migrated_comment.comment_content_src.save(
                f"rh-comment-user-{upserter.id}-thread-{belonging_thread.id}-comment-{migrated_comment.id}.txt",
                comment_content_file,
            )
            migrated_comment.comment_content_json = instance.text
            migrated_comment.save()
        else:
            # Logical ordering. Do not change unless you know what you're doing.
            with transaction.atomic():
                migrated_comment = RhCommentModel.objects.create(
                    comment_content_json=instance.text,
                    comment_content_type=QUILL_EDITOR,  # currently FE utilizes only Quill for
                    created_by=upserter,
                    created_date=instance.created_date,
                    legacy_id=legacy_comment_id,
                    legacy_model_type=LEGACY_COMMENT,
                    thread=belonging_thread,
                    updated_by=upserter,
                )

                # BUUBLE UP: Legacy thread was a type of commenting module. It was NOT merely a grouping tool.
                migrated_legacy_thread_comment = RhCommentModel.objects.filter(
                    legacy_id=legacy_thread.id,
                    legacy_model_type=LEGACY_THREAD,
                ).first() or from_legacy_thread_to_rh_comment(
                    sender, legacy_thread, created, **kwargs
                )
                migrated_comment.parent = migrated_legacy_thread_comment
                migrated_comment.comment_content_src.save(
                    f"rh-comment-user-{upserter.id}-thread-{belonging_thread.id}-comment-{migrated_comment.id}.txt",
                    comment_content_file,
                )

        # intentionally querying DB to ensure that the instance was created properly
        return RhCommentModel.objects.get(
            legacy_id=legacy_comment_id,
            legacy_model_type=LEGACY_COMMENT,
        )

    except Exception as error:
        sentry.log_error("from_legacy_comment_to_rh_comment: ", error)


@receiver(post_save, sender=LegacyReply, dispatch_uid="from_legacy_reply_to_rh_comment")
def from_legacy_reply_to_rh_comment(sender, instance, created, **kwargs):
    try:
        upserter = instance.created_by
        belonging_document = get_belonging_doc(instance)
        belonging_thread = find_or_create_belonging_thread(belonging_document, upserter)
        comment_content_file = ContentFile(
            (json.dumps(instance.text) or instance.plain_text or "").encode()
        )
        # Legacy Reply HAS to have a parent. A parent can be a LegacyReply or LegacyComment
        # However, in FE nested LegacyReply was blocked at some point. Most likely it's LegacyComment
        legacy_parent = instance.parent
        legacy_reply_id = instance.id

        migrated_reply = RhCommentModel.objects.filter(
            legacy_id=legacy_reply_id,
            legacy_model_type=LEGACY_REPLY,
        ).first()

        if migrated_reply is not None:
            # migrated_reply.comment_content_src = comment_content_file
            migrated_reply.comment_content_json = instance.text
            migrated_reply.save()
        else:
            # Logical ordering. Do not change unless you know what you're doing.
            with transaction.atomic():
                migrated_reply = RhCommentModel.objects.create(
                    comment_content_json=instance.text,
                    comment_content_type=QUILL_EDITOR,  # currently FE utilizes only Quill for
                    created_by=upserter,
                    created_date=instance.created_date,
                    legacy_id=legacy_reply_id,
                    legacy_model_type=LEGACY_REPLY,
                    thread=belonging_thread,
                    updated_by=upserter,
                )

                # BUUBLE UP
                is_legacy_parent_a_comment = isinstance(legacy_parent, LegacyComment)
                migrated_legacy_parent = RhCommentModel.objects.filter(
                    legacy_id=legacy_parent.id,
                    legacy_model_type=LEGACY_COMMENT
                    if is_legacy_parent_a_comment
                    else LEGACY_REPLY,
                ).first() or (
                    from_legacy_comment_to_rh_comment(
                        sender, legacy_parent, created, **kwargs
                    )
                    if is_legacy_parent_a_comment
                    else from_legacy_reply_to_rh_comment(
                        sender, legacy_parent, created, **kwargs
                    )
                )
                migrated_reply.parent = migrated_legacy_parent
                migrated_reply.comment_content_src.save(
                    f"rh-comment-user-{upserter.id}-thread-{belonging_thread.id}-comment-{migrated_reply.id}.txt",
                    comment_content_file,
                )

        return RhCommentModel.objects.get(
            legacy_id=legacy_reply_id,
            legacy_model_type=LEGACY_REPLY,
        )

    except Exception as error:
        sentry.log_error("from_legacy_reply_to_rh_comment: ", error)


def get_belonging_doc(instance):
    # currently migration supported documents
    return instance.paper or instance.post or instance.hypothesis or instance.citation


def find_or_create_belonging_thread(belonging_document, upserter):
    return RhCommentThreadModel.objects.filter(
        content_type=ContentType.objects.get_for_model(belonging_document),
        object_id=belonging_document.id,
        thread_type=GENERIC_COMMENT,  # currently only backfilling generic comments
    ).first() or RhCommentThreadModel.objects.create(
        content_type=ContentType.objects.get_for_model(belonging_document),
        created_by=upserter,
        object_id=belonging_document.id,
        thread_type=GENERIC_COMMENT,  # currently only backfilling generic comments
        updated_by=upserter,
    )
