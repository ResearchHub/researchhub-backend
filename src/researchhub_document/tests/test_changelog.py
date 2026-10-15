from datetime import UTC, datetime
from importlib import import_module

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from note.models import Note
from note.tests.helpers import create_note
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    CHANGELOG,
    DISCUSSION,
)
from researchhub_document.views.researchhub_post_views import (
    MIN_POST_BODY_LENGTH,
    MIN_POST_TITLE_LENGTH,
)
from user.tests.helpers import create_random_default_user

mark_existing_changelogs = import_module(
    "researchhub_document.migrations.0084_mark_existing_changelogs"
)


def _post_payload(user, **overrides):
    return {
        "document_type": CHANGELOG,
        "created_by": user.id,
        "full_src": "body",
        "renderable_text": "x" * MIN_POST_BODY_LENGTH,
        "title": "x" * MIN_POST_TITLE_LENGTH,
        **overrides,
    }


class ChangelogPublishTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_default_user("changelog_mod", moderator=True)
        self.user = create_random_default_user("changelog_user")

    def test_moderator_publishes_approved_changelog(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            "/api/researchhubpost/", _post_payload(self.moderator)
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        post = ResearchhubPost.objects.get(id=response.data["id"])
        self.assertEqual(post.document_type, CHANGELOG)
        self.assertEqual(post.unified_document.document_type, CHANGELOG)
        self.assertEqual(
            post.unified_document.status, ResearchhubUnifiedDocument.APPROVED
        )

    def test_non_moderator_cannot_publish_changelog(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post("/api/researchhubpost/", _post_payload(self.user))

        # Assert
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ResearchhubPost.objects.filter(created_by=self.user).exists())

    def test_non_moderator_cannot_turn_post_into_changelog(self):
        # Arrange
        post = create_post(created_by=self.user, document_type=DISCUSSION)
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.put(
            f"/api/researchhubpost/{post.id}/",
            _post_payload(self.user, post_id=post.id),
        )

        # Assert
        self.assertEqual(response.status_code, 403)
        post.refresh_from_db()
        self.assertEqual(post.document_type, DISCUSSION)

    def test_editing_changelog_keeps_its_type(self):
        # Arrange
        post = create_post(created_by=self.moderator, document_type=CHANGELOG)
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.put(
            f"/api/researchhubpost/{post.id}/",
            _post_payload(
                self.moderator,
                post_id=post.id,
                document_type=DISCUSSION,
                authors=[],
            ),
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        post.refresh_from_db()
        self.assertEqual(post.document_type, CHANGELOG)


class ChangelogListTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_default_user("changelog_author", moderator=True)

    def test_lists_public_changelogs_newest_first(self):
        # Arrange
        older = create_post(
            title="Older", created_by=self.moderator, document_type=CHANGELOG
        )
        newer = create_post(
            title="Newer", created_by=self.moderator, document_type=CHANGELOG
        )
        ResearchhubPost.objects.filter(id=older.id).update(
            created_date=datetime(2026, 1, 1, tzinfo=UTC)
        )
        create_post(
            title="Discussion", created_by=self.moderator, document_type=DISCUSSION
        )
        removed = create_post(
            title="Removed", created_by=self.moderator, document_type=CHANGELOG
        )
        ResearchhubUnifiedDocument.objects.filter(
            id=removed.unified_document_id
        ).update(is_removed=True)
        private = create_post(
            title="Private", created_by=self.moderator, document_type=CHANGELOG
        )
        ResearchhubUnifiedDocument.objects.filter(
            id=private.unified_document_id
        ).update(is_public=False)

        # Act
        response = self.client.get("/api/researchhubpost/changelog/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            [post["id"] for post in response.data["results"]], [newer.id, older.id]
        )

    def test_moderators_see_the_public_list(self):
        # Arrange
        moderator = create_random_default_user("changelog_list_mod", moderator=True)
        pending = create_post(
            title="Pending", created_by=self.moderator, document_type=CHANGELOG
        )
        ResearchhubUnifiedDocument.objects.filter(
            id=pending.unified_document_id
        ).update(status=ResearchhubUnifiedDocument.PENDING)
        self.client.force_authenticate(moderator)

        # Act
        response = self.client.get("/api/researchhubpost/changelog/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_paginates_with_page_size(self):
        # Arrange
        for index in range(3):
            create_post(
                title=f"Changelog {index}",
                created_by=self.moderator,
                document_type=CHANGELOG,
            )

        # Act
        response = self.client.get("/api/researchhubpost/changelog/?page_size=2")

        # Assert
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["next"])


class LatestChangelogTests(APITestCase):
    def test_returns_newest_public_changelog(self):
        # Arrange
        moderator = create_random_default_user("latest_author", moderator=True)
        create_post(title="Older", created_by=moderator, document_type=CHANGELOG)
        newer = create_post(
            title="Newer", created_by=moderator, document_type=CHANGELOG
        )
        create_post(title="Discussion", created_by=moderator, document_type=DISCUSSION)

        # Act
        response = self.client.get("/api/researchhubpost/changelog/latest/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], newer.id)

    def test_returns_null_without_changelogs(self):
        # Act
        response = self.client.get("/api/researchhubpost/changelog/latest/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data)


class MarkExistingChangelogsMigrationTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("changelog_migration")
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

    def _create_note(self):
        note, _ = create_note(self.user, None)
        return note

    def _create_discussion_post(self, post_id=None, note=None):
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION
        )
        return ResearchhubPost.objects.create(
            id=post_id,
            created_by=self.user,
            document_type=DISCUSSION,
            note=note,
            title="Changelog",
            unified_document=unified_document,
        )

    def _create_feed_entry(self, post):
        return FeedEntry.objects.create(
            action=FeedEntry.PUBLISH,
            action_date=post.created_date,
            content_type=self.post_content_type,
            object_id=post.id,
            unified_document=post.unified_document,
        )

    def test_retypes_legacy_changelog_posts_and_drops_their_feed_entries(self):
        # Arrange
        legacy_note = self._create_note()
        legacy = self._create_discussion_post(
            post_id=mark_existing_changelogs.LEGACY_CHANGELOG_POST_IDS[-1],
            note=legacy_note,
        )
        other = self._create_discussion_post()
        legacy_entry = self._create_feed_entry(legacy)
        other_entry = self._create_feed_entry(other)

        # Act
        mark_existing_changelogs.mark_changelogs(apps, None)

        # Assert
        legacy.refresh_from_db()
        legacy_note.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(legacy.document_type, CHANGELOG)
        self.assertEqual(legacy.unified_document.document_type, CHANGELOG)
        self.assertEqual(legacy_note.document_type, CHANGELOG)
        self.assertEqual(other.document_type, DISCUSSION)
        self.assertFalse(FeedEntry.objects.filter(id=legacy_entry.id).exists())
        self.assertTrue(FeedEntry.objects.filter(id=other_entry.id).exists())

    def test_retypes_notebook_changelogs_created_after_rollout(self):
        # Arrange
        draft = self._create_note()
        published_note = self._create_note()
        preprint_note = self._create_note()
        Note.objects.filter(id__in=[draft.id, published_note.id]).update(
            document_type=DISCUSSION
        )
        Note.objects.filter(id=preprint_note.id).update(
            document_type=DISCUSSION, created_date=datetime(2026, 1, 1, tzinfo=UTC)
        )
        published = self._create_discussion_post(note=published_note)
        preprint = self._create_discussion_post(note=preprint_note)

        # Act
        mark_existing_changelogs.mark_changelogs(apps, None)

        # Assert
        for record in (draft, published_note, preprint_note, published, preprint):
            record.refresh_from_db()
        self.assertEqual(draft.document_type, CHANGELOG)
        self.assertEqual(published_note.document_type, CHANGELOG)
        self.assertEqual(published.document_type, CHANGELOG)
        self.assertEqual(preprint_note.document_type, DISCUSSION)
        self.assertEqual(preprint.document_type, DISCUSSION)

    def test_reverse_restores_discussion(self):
        # Arrange
        post = create_post(created_by=self.user, document_type=CHANGELOG)

        # Act
        mark_existing_changelogs.unmark_changelogs(apps, None)

        # Assert
        post.refresh_from_db()
        self.assertEqual(post.document_type, DISCUSSION)
        self.assertEqual(post.unified_document.document_type, DISCUSSION)
