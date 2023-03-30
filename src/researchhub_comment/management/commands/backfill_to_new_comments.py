import json
from threading import Thread as PyThread

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
            return old_obj.calculate_score()

        score = 0
        for old_vote in old_obj.votes.all().iterator():
            vote_type = old_vote.vote_type
            if vote_type == Vote.UPVOTE:
                score += 1
            else:
                score -= 1
            Vote.objects.create(
                object_id=new_obj.id,
                content_type=get_content_type_for_model(new_obj),
                created_by=old_vote.created_by,
                vote_type=vote_type,
            )
        return score

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

    def _handle_new_threads(self, start, end, exclude_ids):
        threads = (
            Thread.objects.exclude(id__in=exclude_ids)
            .filter(id__gte=start, id__lt=end)
            .order_by("id")
        )
        thread_count = threads.count()
        for i, thread in enumerate(threads.iterator()):
            print(f"THREAD: {i}/{thread_count}")
            try:
                created_by = thread.created_by
                document = thread.unified_document.get_document()
                discussion_post_type = thread.discussion_post_type
                belonging_thread = RhCommentThreadModel.objects.create(
                    content_type=ContentType.objects.get_for_model(document),
                    created_by=created_by,
                    object_id=document.id,
                    updated_by=created_by,
                    thread_type=discussion_post_type,
                )

                migrated_thread_comment = RhCommentModel.all_objects.create(
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

                score = self._create_votes_for_discussion(
                    thread, migrated_thread_comment
                )
                RhCommentModel.objects.filter(id=migrated_thread_comment.id).update(
                    score=score,
                    created_date=thread.created_date,
                    updated_date=thread.updated_date,
                )
            except Exception as e:
                print(f"thread id: {thread.id}: {e}")

    def _handle_threads(self):
        existing_threads = RhCommentModel.all_objects.filter(
            legacy_model_type=LEGACY_THREAD
        ).order_by("id")
        existing_thread_ids = existing_threads.values_list("legacy_id")
        threads = Thread.objects.exclude(id__in=existing_thread_ids).order_by("id")

        existing_threads_count = existing_threads.count()
        for i, existing_thread in enumerate(existing_threads.iterator()):
            print(f"EXISTING THREADS: {i}/{existing_threads_count}")
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
                score = self._create_votes_for_discussion(
                    connecting_thread, existing_thread
                )
                RhCommentModel.objects.filter(id=existing_thread.id).update(
                    score=score,
                    created_date=connecting_thread.created_date,
                    updated_date=connecting_thread.updated_date,
                )
            except Exception as e:
                print(e)

        if threads.count() == 0:
            return

        CHUNK_SIZE = 5000
        start = threads.first().id
        end = threads.last().id

        py_threads = []
        for i in range(start, end + CHUNK_SIZE, CHUNK_SIZE):
            t = PyThread(
                target=self._handle_new_threads,
                args=(i, i + CHUNK_SIZE, existing_thread_ids),
            )
            t.daemon = True
            t.start()
            py_threads.append(t)

        for t in py_threads:
            t.join()

    def _handle_new_comments(self, start, end, exclude_ids):
        comments = (
            Comment.objects.exclude(id__in=exclude_ids)
            .filter(id__gte=start, id__lt=end)
            .order_by("id")
        )
        comment_count = comments.count()
        for i, comment in enumerate(comments.iterator()):
            try:
                print(f"COMMENT: {i}/{comment_count}")
                created_by = comment.created_by
                document = comment.unified_document.get_document()
                belonging_thread = self._get_rh_thread(document, created_by)
                parent = RhCommentModel.all_objects.get(
                    legacy_id=comment.thread.id,
                    legacy_model_type=LEGACY_THREAD,
                )
                migrated_comment = RhCommentModel.all_objects.create(
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

                score = self._create_votes_for_discussion(comment, migrated_comment)
                RhCommentModel.objects.filter(id=migrated_comment.id).update(
                    score=score,
                    created_date=comment.created_date,
                    updated_date=comment.updated_date,
                )
            except Exception as e:
                print(f"comment id: {comment.id}: {e}")

    def _handle_comments(self):
        existing_comments = RhCommentModel.all_objects.filter(
            legacy_model_type=LEGACY_COMMENT
        ).order_by("id")
        existing_comment_ids = existing_comments.values_list("legacy_id", flat=True)
        comments = Comment.objects.exclude(id__in=existing_comment_ids).order_by("id")

        existing_comments_count = existing_comments.count()
        for i, existing_comment in enumerate(existing_comments.iterator()):
            print(f"EXISTING COMMENTS: {i}/{existing_comments_count}")
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
                score = self._create_votes_for_discussion(
                    connecting_comment, existing_comment
                )
                RhCommentModel.objects.filter(id=existing_comment.id).update(
                    score=score,
                    created_date=connecting_comment.created_date,
                    updated_date=connecting_comment.updated_date,
                )
            except Exception as e:
                print(e)

        if comments.count() == 0:
            return

        CHUNK_SIZE = 1000
        start = comments.first().id
        end = comments.last().id

        py_threads = []
        for i in range(start, end + CHUNK_SIZE, CHUNK_SIZE):
            t = PyThread(
                target=self._handle_new_comments,
                args=(i, i + CHUNK_SIZE, existing_comment_ids),
            )
            t.daemon = True
            t.start()
            py_threads.append(t)

        for t in py_threads:
            t.join()

    def _handle_new_replies(self, start, end, exclude_ids):
        replies = (
            Reply.objects.exclude(id__in=exclude_ids)
            .filter(id__gte=start, id__lt=end)
            .order_by("id")
        )
        reply_count = replies.count()
        for i, reply in enumerate(replies.iterator()):
            print(f"REPLY: {i}/{reply_count}")
            try:
                created_by = reply.created_by
                document = reply.unified_document.get_document()
                belonging_thread = self._get_rh_thread(document, created_by)
                parent = RhCommentModel.all_objects.get(
                    legacy_id=reply.parent.id,
                    legacy_model_type=LEGACY_COMMENT,
                )
                migrated_reply = RhCommentModel.all_objects.create(
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

                score = self._create_votes_for_discussion(reply, migrated_reply)
                RhCommentModel.objects.filter(id=migrated_reply.id).update(
                    score=score,
                    created_date=reply.created_date,
                    updated_date=reply.updated_date,
                )
            except Exception as e:
                print(f"reply id: {reply.id}: {e}")

    def _handle_replies(self):
        existing_replies = RhCommentModel.all_objects.filter(
            legacy_model_type=LEGACY_REPLY
        ).order_by("id")
        existing_reply_ids = existing_replies.values_list("legacy_id", flat=True)
        replies = Reply.objects.exclude(id__in=existing_reply_ids).order_by("id")

        existing_replies_count = existing_replies.count()
        for i, existing_reply in enumerate(existing_replies.iterator()):
            print(f"EXISTING REPLIES: {i}/{existing_replies_count}")
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
                score = self._create_votes_for_discussion(
                    connecting_reply, existing_reply
                )
                RhCommentModel.objects.filter(id=existing_reply.id).update(
                    score=score,
                    created_date=connecting_reply.created_date,
                    updated_date=connecting_reply.updated_date,
                )
            except Exception as e:
                print(e)

        if replies.count() == 0:
            return

        CHUNK_SIZE = 1000
        start = replies.first().id
        end = replies.last().id

        py_threads = []
        for i in range(start, end + CHUNK_SIZE, CHUNK_SIZE):
            t = PyThread(
                target=self._handle_new_replies,
                args=(i, i + CHUNK_SIZE, existing_reply_ids),
            )
            t.daemon = True
            t.start()
            py_threads.append(t)

        for t in py_threads:
            t.join()

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
#         rh_comment = RhCommentModel.all_objects.get(
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
#         rh_comment = RhCommentModel.all_objects.get(
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
#         rh_comment = RhCommentModel.all_objects.get(
#             legacy_id=reply.id,
#             legacy_model_type=LEGACY_REPLY
#         )
#         rh_comment.is_removed = reply.is_removed
#         rh_comment.is_public = reply.is_public
#         rh_comment.save()
#     except Exception as e:
#         print(e)
