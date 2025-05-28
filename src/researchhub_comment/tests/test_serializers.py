from unittest.mock import Mock

from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from researchhub_comment.models import RhCommentThreadModel
from researchhub_comment.serializers import DynamicRhThreadSerializer
from user.tests.helpers import create_random_default_user


class DynamicRhThreadSerializerTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("test_user")
        self.paper = create_paper(uploaded_by=self.user)

    def _create_paper_comment(
        self, paper_id, created_by, text="test comment", **kwargs
    ):
        """Helper to create a comment on a paper."""
        self.client.force_authenticate(created_by)
        res = self.client.post(
            f"/api/paper/{paper_id}/comments/create_rh_comment/",
            {
                "comment_content_json": {"ops": [{"insert": text}]},
                **kwargs,
            },
        )
        return res

    def test_content_object_fields_for_paper(self):
        """Test content_object_id and content_object_type for papers."""
        # Create a comment thread for the paper
        comment_response = self._create_paper_comment(self.paper.id, self.user)
        self.assertEqual(comment_response.status_code, 200)

        # Get the thread from the database
        thread = RhCommentThreadModel.objects.get(
            object_id=self.paper.id, content_type__model="paper"
        )

        # Serialize the thread
        serializer = DynamicRhThreadSerializer(thread)
        data = serializer.data

        # Assert the new fields are present and correct
        self.assertIn("content_object_id", data)
        self.assertIn("content_object_type", data)
        self.assertEqual(data["content_object_id"], self.paper.id)
        self.assertEqual(data["content_object_type"], "paper")

    def test_content_object_fields_with_none_content(self):
        """Test content_object_id and content_object_type with None content."""
        # Mock a thread with None content object
        mock_thread = Mock()
        mock_thread.content_object = None

        serializer = DynamicRhThreadSerializer()

        # Test the methods directly
        content_object_id = serializer.get_content_object_id(mock_thread)
        content_object_type = serializer.get_content_object_type(mock_thread)

        # Assert the new fields handle None gracefully
        self.assertIsNone(content_object_id)
        self.assertIsNone(content_object_type)

    def test_content_object_fields_in_api_response(self):
        """Test that the new fields appear in actual API responses."""
        # Create a comment
        comment_response = self._create_paper_comment(self.paper.id, self.user)
        self.assertEqual(comment_response.status_code, 200)

        # Get the paper details which should include thread information
        self.client.force_authenticate(self.user)
        paper_response = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_response.status_code, 200)

        # Check if discussions field contains our new fields
        discussions = paper_response.data.get("discussions", [])
        if discussions:
            thread_data = discussions[0]
            self.assertIn("content_object_id", thread_data)
            self.assertIn("content_object_type", thread_data)
            self.assertEqual(thread_data["content_object_id"], self.paper.id)
            self.assertEqual(thread_data["content_object_type"], "paper")

    def test_serializer_methods_with_mock_paper(self):
        """Test serializer methods with a mock paper object."""
        # Mock a paper object
        mock_paper = Mock()
        mock_paper.id = 123
        mock_paper._meta.model_name = "paper"

        # Mock a thread with the paper as content object
        mock_thread = Mock()
        mock_thread.content_object = mock_paper

        serializer = DynamicRhThreadSerializer()

        # Test the methods directly
        content_object_id = serializer.get_content_object_id(mock_thread)
        content_object_type = serializer.get_content_object_type(mock_thread)

        # Assert the values are correct
        self.assertEqual(content_object_id, 123)
        self.assertEqual(content_object_type, "paper")

    def test_serializer_fields_consistency(self):
        """Test that the serializer consistently includes the new fields."""
        # Create a comment thread for the paper
        comment_response = self._create_paper_comment(self.paper.id, self.user)
        self.assertEqual(comment_response.status_code, 200)

        # Get the thread from the database
        thread = RhCommentThreadModel.objects.get(
            object_id=self.paper.id, content_type__model="paper"
        )

        # Serialize the thread multiple times to ensure consistency
        for _ in range(3):
            serializer = DynamicRhThreadSerializer(thread)
            data = serializer.data

            # Verify fields are always present
            self.assertIn("content_object_id", data)
            self.assertIn("content_object_type", data)

            # Verify values are consistent
            self.assertEqual(data["content_object_id"], self.paper.id)
            self.assertEqual(data["content_object_type"], "paper")
