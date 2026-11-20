from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from note.tests.helpers import create_note
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost
from researchhub_document.services.post_image_service import (
    is_post_upload_key,
    validate_post_image_key,
)
from researchhub_document.views import researchhub_post_views
from user.tests.helpers import create_random_default_user

LONG_TEXT = "sufficiently long body. " * 4
LONG_TITLE = "sufficiently long title. sufficiently long title."
LEGITIMATE_BODY = (
    '<h2 data-id="a" id="a" data-toc-id="b">Methods</h2>'
    '<p data-id="c">See <a target="_blank" rel="noopener noreferrer nofollow" '
    'class="link" href="https://example.org/?a=1&amp;b=2">this</a></p>'
    '<figure class="image"><img src="https://example.org/a.png" alt="plot">'
    "<figcaption>Figure 1</figcaption></figure>"
)
HOSTILE_BODY = (
    "<p onclick=alert(1)>Intro</p>"
    "<figure><img src=x onerror=alert(1)></figure>"
    '<a href=" JaVaScRiPt:alert(1)">link</a>'
    "<script>alert(1)</script>"
)
CLEANED_HOSTILE_BODY = '<p>Intro</p><figure><img src="x"></figure><a>link</a>'


class StoredBodyCapture:
    def capture_stored_body(self):
        stored = []

        def capture(content):
            stored.append(content)
            return ContentFile(content)

        patcher = patch.object(
            researchhub_post_views, "ContentFile", side_effect=capture
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return stored


class PostBodySanitizingTests(StoredBodyCapture, APITestCase):
    def setUp(self):
        self.user = create_random_default_user("rich_text_author")
        self.client.force_authenticate(self.user)
        self.stored = self.capture_stored_body()

    def _payload(self, **overrides):
        return {
            "document_type": "DISCUSSION",
            "full_src": LEGITIMATE_BODY,
            "renderable_text": LONG_TEXT,
            "title": LONG_TITLE,
            **overrides,
        }

    def _create_post(self, **overrides):
        return self.client.post(
            "/api/researchhubpost/", self._payload(**overrides), format="json"
        )

    def test_create_stores_legitimate_body_unchanged(self):
        # Act
        response = self._create_post()

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stored, [LEGITIMATE_BODY.encode()])

    def test_create_stores_cleaned_body(self):
        # Act
        response = self._create_post(full_src=HOSTILE_BODY)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stored, [CLEANED_HOSTILE_BODY.encode()])

    def test_update_stores_cleaned_body(self):
        # Arrange
        post_id = self._create_post().data["id"]
        self.stored.clear()

        # Act
        response = self.client.post(
            "/api/researchhubpost/",
            self._payload(post_id=post_id, full_src=HOSTILE_BODY),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stored, [CLEANED_HOSTILE_BODY.encode()])

    def test_update_stores_legitimate_body_unchanged(self):
        # Arrange
        post_id = self._create_post().data["id"]
        self.stored.clear()

        # Act
        response = self.client.post(
            "/api/researchhubpost/",
            self._payload(post_id=post_id),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stored, [LEGITIMATE_BODY.encode()])


class StoredPostBodyServingTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("stored_body_author")

    def _post_with_body(self, body):
        post = create_post(created_by=self.user)
        post.discussion_src.save("body.txt", ContentFile(body.encode()))
        return post

    def test_stored_hostile_body_is_cleaned_when_read(self):
        # Arrange
        post = self._post_with_body(HOSTILE_BODY)

        # Act
        body = post.get_full_markdown()

        # Assert
        self.assertEqual(body, CLEANED_HOSTILE_BODY)

    def test_reading_leaves_the_stored_file_untouched(self):
        # Arrange
        post = self._post_with_body(HOSTILE_BODY)

        # Act
        post.get_full_markdown()

        # Assert
        with post.discussion_src.open() as file:
            self.assertEqual(file.read().decode(), HOSTILE_BODY)

    def test_stored_legitimate_body_is_served_unchanged(self):
        # Arrange
        post = self._post_with_body(LEGITIMATE_BODY)

        # Act
        body = post.get_full_markdown()

        # Assert
        self.assertEqual(body, LEGITIMATE_BODY)


class PostImageKeyApiTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("image_owner")
        self.other_user = create_random_default_user("image_other")
        self.own_key = f"uploads/posts/users/{self.user.id}/abc/cover.png"
        self.other_key = f"uploads/posts/users/{self.other_user.id}/abc/cover.png"
        self.client.force_authenticate(self.user)

    def _submit(self, **overrides):
        return self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "full_src": "body",
                "renderable_text": LONG_TEXT,
                "title": LONG_TITLE,
                **overrides,
            },
            format="json",
        )

    def test_create_accepts_own_upload(self):
        # Act
        response = self._submit(image=self.own_key)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ResearchhubPost.objects.get(id=response.data["id"]).image, self.own_key
        )

    def test_create_without_image_is_allowed(self):
        for payload in ({}, {"image": None}, {"image": ""}):
            with self.subTest(payload=payload):
                self.assertEqual(self._submit(**payload).status_code, 200)

    def test_create_rejects_key_outside_own_prefix(self):
        for key in (
            self.other_key,
            "quarantine/uploads/posts/users/1/a.png",
            "uploads/private/secret.pdf",
            f"uploads/posts/users/{self.user.id}/../{self.other_user.id}/a.png",
            f"uploads/posts/users/{self.user.id}/",
            f"uploads/posts/users/{self.user.id}",
            f"https://evil.example/uploads/posts/users/{self.user.id}/a.png",
            ["not", "a", "string"],
        ):
            with self.subTest(key=key):
                # Arrange
                post_count = ResearchhubPost.objects.count()

                # Act
                response = self._submit(image=key)

                # Assert
                self.assertEqual(response.status_code, 400)
                self.assertEqual(ResearchhubPost.objects.count(), post_count)

    def test_create_accepts_cover_chosen_on_the_published_note(self):
        # Arrange
        note, _ = create_note(self.user, self.user.organization)
        note.image = self.other_key
        note.save(update_fields=["image"])

        # Act
        response = self._submit(image=self.other_key, note_id=note.id)

        # Assert
        self.assertEqual(response.status_code, 200)

    def test_create_rejects_note_image_that_is_not_a_post_upload(self):
        # Arrange
        note, _ = create_note(self.user, self.user.organization)
        note.image = "uploads/private/secret.pdf"
        note.save(update_fields=["image"])

        # Act
        response = self._submit(image=note.image, note_id=note.id)

        # Assert
        self.assertEqual(response.status_code, 400)

    def test_update_keeps_existing_image_of_another_user(self):
        # Arrange
        post_id = self._submit().data["id"]
        ResearchhubPost.objects.filter(id=post_id).update(image=self.other_key)

        # Act
        response = self._submit(post_id=post_id, image=self.other_key)

        # Assert
        self.assertEqual(response.status_code, 200)

    def test_update_accepts_new_own_upload(self):
        # Arrange
        post_id = self._submit().data["id"]

        # Act
        response = self._submit(post_id=post_id, image=self.own_key)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ResearchhubPost.objects.get(id=post_id).image, self.own_key)

    def test_update_rejects_new_key_of_another_user(self):
        # Arrange
        post_id = self._submit(image=self.own_key).data["id"]

        # Act
        response = self._submit(post_id=post_id, image=self.other_key)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ResearchhubPost.objects.get(id=post_id).image, self.own_key)


class PostImageKeyValidationTests(SimpleTestCase):
    class User:
        id = 5

    def test_upload_key_must_belong_to_the_given_user(self):
        self.assertTrue(is_post_upload_key("uploads/posts/users/5/a/b.png", 5))
        self.assertFalse(is_post_upload_key("uploads/posts/users/51/a/b.png", 5))
        self.assertFalse(is_post_upload_key("uploads/posts/users/5/a/b.png", 51))

    def test_upload_key_rejects_traversal_and_empty_segments(self):
        for key in (
            "uploads/posts/users/5/../6/b.png",
            "uploads/posts/users/5//b.png",
            "uploads/posts/users/5/",
            "/uploads/posts/users/5/b.png",
            "uploads/posts/users/x/b.png",
            None,
            5,
        ):
            with self.subTest(key=key):
                self.assertFalse(is_post_upload_key(key))

    def test_unchanged_image_is_allowed_whatever_its_shape(self):
        # Act / Assert
        validate_post_image_key(
            "legacy/a.png", self.User, existing_image="legacy/a.png"
        )

    def test_other_key_is_rejected(self):
        # Act / Assert
        with self.assertRaises(ValidationError):
            validate_post_image_key("legacy/a.png", self.User)
