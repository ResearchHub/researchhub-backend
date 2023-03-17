import json

from django.contrib.admin.options import get_content_type_for_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from discussion.models import Comment, Reply, Thread
from discussion.reaction_models import Vote
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.constants.rh_comment_migration_legacy_types import (
    LEGACY_COMMENT,
    LEGACY_REPLY,
    LEGACY_THREAD,
)
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel


class Command(BaseCommand):
    def _create_votes_for_discussion(self, old_obj, new_obj):
        if old_obj.votes.count() == new_obj.votes.count():
            return

        for old_vote in old_obj.votes.all().iterator():
            vote_type = old_vote.vote_type
            Vote.objects.create(
                object_id=new_obj.id,
                content_type=get_content_type_for_model(new_obj),
                created_by=old_vote.created_by,
                vote_type=vote_type,
            )

    def _get_rh_thread(
        self, document, created_by, discussion_post_type=GENERIC_COMMENT
    ):
        if discussion_post_type == "DISCUSSION":
            discussion_post_type = GENERIC_COMMENT

        return RhCommentThreadModel.objects.filter(
            content_type=ContentType.objects.get_for_model(document),
            object_id=document.id,
            thread_type=GENERIC_COMMENT,
        ).first() or RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(document),
            created_by=created_by,
            object_id=document.id,
            updated_by=created_by,
            thread_type=discussion_post_type,
        )

    def _handle_threads(self):
        existing_threads = RhCommentModel.objects.filter(
            legacy_model_type=LEGACY_THREAD
        )
        existing_thread_ids = existing_threads.values_list("legacy_id")
        threads = Thread.objects.exclude(id__in=existing_thread_ids)

        existing_threads_count = existing_threads.count()
        for i, existing_thread in enumerate(existing_threads.iterator()):
            print(f"{i}/{existing_threads_count}")
            try:
                comment_content_json = existing_thread.comment_content_json
                if not comment_content_json or not isinstance(
                    comment_content_json, dict
                ):
                    content = existing_thread.comment_content_src.read().decode("utf8")
                    try:
                        existing_thread.comment_content_json = json.loads(content)
                    except json.JSONDecodeError:
                        existing_thread.comment_content_json = {
                            "ops": [{"insert": content}]
                        }
                    finally:
                        existing_thread.save()

                connecting_thread = Thread.objects.get(id=existing_thread.legacy_id)
                self._create_votes_for_discussion(connecting_thread, existing_thread)
            except Exception as e:
                print(e)

        thread_count = threads.count()
        for i, thread in enumerate(threads.iterator()):
            print(f"{i}/{thread_count}")
            try:
                created_by = thread.created_by
                document = thread.unified_document.get_document()
                discussion_post_type = thread.discussion_post_type
                belonging_thread = self._get_rh_thread(
                    document, created_by, discussion_post_type
                )
                migrated_thread_comment = RhCommentModel.objects.create(
                    comment_content_json=thread.text,
                    comment_content_type=QUILL_EDITOR,
                    context_title=thread.context_title,
                    created_by=created_by,
                    created_date=thread.created_date,
                    legacy_id=thread.id,
                    legacy_model_type=LEGACY_THREAD,
                    thread=belonging_thread,
                    updated_by=created_by,
                    is_removed=thread.is_removed,
                    is_public=thread.is_public,
                    is_accepted_answer=thread.is_accepted_answer,
                )
                text = thread.text
                if text:
                    content = json.dumps(text)
                else:
                    content = json.dumps({"ops": [{"insert": thread.plain_text or ""}]})

                comment_content_file = ContentFile(content.encode("utf8"))
                migrated_thread_comment.comment_content_src.save(
                    f"rh-comment-user-{created_by.id}-thread-{belonging_thread.id}-comment-{migrated_thread_comment.id}.txt",
                    comment_content_file,
                )

                self._create_votes_for_discussion(thread, migrated_thread_comment)
            except Exception as e:
                print(f"thread id: {thread.id}: {e}")

    def _handle_comments(self):
        existing_comments = RhCommentModel.objects.filter(
            legacy_model_type=LEGACY_COMMENT
        )
        existing_comment_ids = existing_comments.values_list("legacy_id")
        comments = Comment.objects.exclude(id__in=existing_comment_ids)

        existing_comments_count = existing_comments.count()
        for i, existing_comment in enumerate(existing_comments.iterator()):
            print(f"{i}/{existing_comments_count}")
            try:
                comment_content_json = existing_comment.comment_content_json
                if not comment_content_json or not isinstance(
                    comment_content_json, dict
                ):
                    content = existing_comment.comment_content_src.read().decode("utf8")
                    try:
                        existing_comment.comment_content_json = json.loads(content)
                    except json.JSONDecodeError:
                        existing_comment.comment_content_json = {
                            "ops": [{"insert": content}]
                        }
                    finally:
                        existing_comment.save()

                connecting_comment = Comment.objects.get(id=existing_comment.legacy_id)
                self._create_votes_for_discussion(connecting_comment, existing_comment)
            except Exception as e:
                print(e)

        comment_count = comments.count()
        for i, comment in enumerate(comments.iterator()):
            try:
                print(f"{i}/{comment_count}")
                created_by = comment.created_by
                document = comment.unified_document.get_document()
                belonging_thread = self._get_rh_thread(document, created_by)
                parent = RhCommentModel.objects.get(
                    legacy_id=comment.thread.id,
                    legacy_model_type=LEGACY_THREAD,
                )
                migrated_comment = RhCommentModel.objects.create(
                    comment_content_json=comment.text,
                    comment_content_type=QUILL_EDITOR,
                    created_by=created_by,
                    created_date=comment.created_date,
                    legacy_id=comment.id,
                    legacy_model_type=LEGACY_COMMENT,
                    thread=belonging_thread,
                    updated_by=created_by,
                    parent=parent,
                    is_removed=comment.is_removed,
                    is_public=comment.is_public,
                    is_accepted_answer=comment.is_accepted_answer,
                )
                text = comment.text
                if text:
                    content = json.dumps(text)
                else:
                    content = json.dumps(
                        {"ops": [{"insert": comment.plain_text or ""}]}
                    )

                comment_content_file = ContentFile(content.encode("utf8"))
                migrated_comment.comment_content_src.save(
                    f"rh-comment-user-{created_by.id}-thread-{belonging_thread.id}-comment-{migrated_comment.id}.txt",
                    comment_content_file,
                )

                self._create_votes_for_discussion(comment, migrated_comment)
            except Exception as e:
                print(f"comment id: {comment.id}: {e}")

    def _handle_replies(self):
        existing_replies = RhCommentModel.objects.filter(
            legacy_model_type=LEGACY_COMMENT
        )
        existing_reply_ids = existing_replies.values_list("legacy_id")
        replies = Reply.objects.exclude(id__in=existing_reply_ids)

        existing_replies_count = existing_replies.count()
        for i, existing_reply in enumerate(existing_replies.iterator()):
            print(f"{i}/{existing_replies_count}")
            try:
                comment_content_json = existing_reply.comment_content_json
                if not comment_content_json or not isinstance(
                    comment_content_json, dict
                ):
                    content = existing_reply.comment_content_src.read().decode("utf8")
                    try:
                        existing_reply.comment_content_json = json.loads(content)
                    except json.JSONDecodeError:
                        existing_reply.comment_content_json = {
                            "ops": [{"insert": content}]
                        }
                    finally:
                        existing_reply.save()

                connecting_reply = Comment.objects.get(id=existing_reply.legacy_id)
                self._create_votes_for_discussion(connecting_reply, existing_reply)
            except Exception as e:
                print(e)

        reply_count = replies.count()
        for i, reply in enumerate(replies.iterator()):
            print(f"{i}/{reply_count}")
            try:
                created_by = reply.created_by
                document = reply.unified_document.get_document()
                belonging_thread = self._get_rh_thread(document, created_by)
                parent = RhCommentModel.objects.get(
                    legacy_id=reply.parent.id,
                    legacy_model_type=LEGACY_COMMENT,
                )
                migrated_reply = RhCommentModel.objects.create(
                    comment_content_json=reply.text,
                    comment_content_type=QUILL_EDITOR,
                    created_by=created_by,
                    created_date=reply.created_date,
                    legacy_id=reply.id,
                    legacy_model_type=LEGACY_REPLY,
                    thread=belonging_thread,
                    updated_by=created_by,
                    parent=parent,
                    is_removed=reply.is_removed,
                    is_public=reply.is_public,
                )

                text = reply.text
                if text:
                    content = json.dumps(text)
                else:
                    content = json.dumps({"ops": [{"insert": reply.plain_text or ""}]})

                comment_content_file = ContentFile(content.encode("utf8"))
                migrated_reply.comment_content_src.save(
                    f"rh-comment-user-{created_by.id}-thread-{belonging_thread.id}-comment-{migrated_reply.id}.txt",
                    comment_content_file,
                )

                self._create_votes_for_discussion(reply, migrated_reply)
            except Exception as e:
                print(f"reply id: {reply.id}: {e}")

    def handle(self, *args, **options):
        self._handle_threads()
        self._handle_comments()
        self._handle_replies()


# from researchhub_comment.constants.rh_comment_migration_legacy_types import (
#     LEGACY_COMMENT,
#     LEGACY_REPLY,
#     LEGACY_THREAD,
# )

# threads = Thread.objects.all()
# comments = Comment.objects.all()
# replies = Reply.objects.all()

# for thread in threads.iterator():
#     try:
#         rh_comment = RhCommentModel.objects.get(
#             legacy_id=thread.id,
#             legacy_model_type=LEGACY_THREAD
#         )
#         rh_comment.is_removed = thread.is_removed
#         rh_comment.is_public = thread.is_public
#         rh_comment.save()
#     except Exception as e:
#         print(e)

# for comment in comments.iterator():
#     try:
#         rh_comment = RhCommentModel.objects.get(
#             legacy_id=comment.id,
#             legacy_model_type=LEGACY_COMMENT
#         )
#         rh_comment.is_removed = comment.is_removed
#         rh_comment.is_public = comment.is_public
#         rh_comment.save()
#     except Exception as e:
#         print(e)

# for reply in replies.iterator():
#     try:
#         rh_comment = RhCommentModel.objects.get(
#             legacy_id=reply.id,
#             legacy_model_type=LEGACY_REPLY
#         )
#         rh_comment.is_removed = reply.is_removed
#         rh_comment.is_public = reply.is_public
#         rh_comment.save()
#     except Exception as e:
#         print(e)
