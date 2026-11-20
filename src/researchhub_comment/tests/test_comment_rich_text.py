import copy
from unittest.mock import patch

from rest_framework.test import APITestCase

from researchhub_comment.constants.rh_comment_content_types import TIPTAP
from researchhub_comment.models import RhCommentModel
from researchhub_comment.related_models import rh_comment_model
from researchhub_comment.serializers import (
    DynamicRhCommentSerializer,
    RhCommentSerializer,
)
from researchhub_comment.tests.helpers import create_rh_comment
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user

LEGITIMATE_COMMENT = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "See <b>this</b> "},
                {
                    "type": "text",
                    "text": "paper",
                    "marks": [
                        {
                            "type": "link",
                            "attrs": {"href": "https://doi.org/10.1000/1"},
                        }
                    ],
                },
            ],
        },
        {"type": "image", "attrs": {"src": "https://example.org/a.png"}},
    ],
}
HOSTILE_COMMENT = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "attrs": {"onclick": "alert(1)"},
            "content": [
                {
                    "type": "text",
                    "text": "label",
                    "marks": [
                        {
                            "type": "link",
                            "attrs": {"href": "\tJaVaScRiPt:alert(1)"},
                        }
                    ],
                },
                {"type": "richLink", "attrs": {"url": "javascript:alert(1)"}},
            ],
        },
        {"type": "image", "attrs": {"src": "javascript:alert(1)"}},
    ],
}
CLEANED_COMMENT = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "attrs": {},
            "content": [
                {"type": "text", "text": "label", "marks": []},
                {"type": "richLink", "attrs": {"url": ""}},
            ],
        },
        {"type": "image", "attrs": {"src": ""}},
    ],
}


class CommentContentSanitizingTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("comment_author")
        self.post = create_post(created_by=self.user)
        self.client.force_authenticate(self.user)
        self.url = f"/api/researchhubpost/{self.post.id}/comments/"

    def _create_comment(self, content):
        return self.client.post(
            f"{self.url}create_rh_comment/",
            {"comment_content_json": content, "comment_content_type": TIPTAP},
            format="json",
        )

    def test_hostile_comment_is_cleaned_before_storing(self):
        # Act
        response = self._create_comment(copy.deepcopy(HOSTILE_COMMENT))

        # Assert
        self.assertEqual(response.status_code, 200)
        comment = RhCommentModel.objects.get(id=response.data["id"])
        self.assertEqual(comment.comment_content_json, CLEANED_COMMENT)
        self.assertEqual(response.data["comment_content_json"], CLEANED_COMMENT)

    def test_stored_source_file_receives_the_cleaned_comment(self):
        # Act
        with patch.object(
            rh_comment_model.celery_create_comment_content_src, "apply_async"
        ) as apply_async:
            response = self._create_comment(copy.deepcopy(HOSTILE_COMMENT))

        # Assert
        self.assertEqual(response.status_code, 200)
        _, stored_content = apply_async.call_args.args[0]
        self.assertEqual(stored_content, CLEANED_COMMENT)

    def test_legitimate_comment_is_stored_unchanged(self):
        # Act
        response = self._create_comment(copy.deepcopy(LEGITIMATE_COMMENT))

        # Assert
        self.assertEqual(response.status_code, 200)
        comment = RhCommentModel.objects.get(id=response.data["id"])
        self.assertEqual(comment.comment_content_json, LEGITIMATE_COMMENT)

    def test_quill_comment_links_are_cleaned(self):
        # Act
        response = self.client.post(
            f"{self.url}create_rh_comment/",
            {
                "comment_content_json": {
                    "ops": [
                        {
                            "insert": "label",
                            "attributes": {"link": "javascript:alert(1)"},
                        }
                    ]
                },
                "comment_content_type": "QUILL_EDITOR",
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        comment = RhCommentModel.objects.get(id=response.data["id"])
        self.assertEqual(
            comment.comment_content_json,
            {"ops": [{"insert": "label", "attributes": {}}]},
        )

    def test_editing_a_comment_cleans_its_content(self):
        # Arrange
        comment_id = self._create_comment(copy.deepcopy(LEGITIMATE_COMMENT)).data["id"]

        # Act
        response = self.client.patch(
            f"{self.url}{comment_id}/",
            {"comment_content_json": copy.deepcopy(HOSTILE_COMMENT)},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        comment = RhCommentModel.objects.get(id=comment_id)
        self.assertEqual(comment.comment_content_json, CLEANED_COMMENT)


class StoredCommentServingTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("stored_comment_author")
        self.post = create_post(created_by=self.user)
        self.comment = create_rh_comment(post=self.post, created_by=self.user)
        RhCommentModel.objects.filter(id=self.comment.id).update(
            comment_content_json=HOSTILE_COMMENT,
            comment_content_type=TIPTAP,
        )
        self.comment.refresh_from_db()

    def test_stored_hostile_comment_is_cleaned_when_read_through_the_api(self):
        # Act
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/{self.comment.id}/"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["comment_content_json"], CLEANED_COMMENT)

    def test_serializers_clean_without_changing_the_stored_row(self):
        for serializer_class in (RhCommentSerializer, DynamicRhCommentSerializer):
            with self.subTest(serializer=serializer_class.__name__):
                # Act
                data = serializer_class(
                    self.comment,
                    **(
                        {"_include_fields": ("id", "comment_content_json")}
                        if serializer_class is DynamicRhCommentSerializer
                        else {}
                    ),
                ).data

                # Assert
                self.assertEqual(data["comment_content_json"], CLEANED_COMMENT)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.comment_content_json, HOSTILE_COMMENT)

    def test_field_exclusion_is_respected(self):
        # Act
        data = DynamicRhCommentSerializer(self.comment, _include_fields=("id",)).data

        # Assert
        self.assertNotIn("comment_content_json", data)
