from unittest.mock import Mock, patch

from django.test import TestCase

from paper.tests.helpers import create_paper
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from search.tasks import update_user_related_documents
from user.tests.helpers import create_random_authenticated_user


class UserSearchDocumentUpdateTaskTests(TestCase):
    def setUp(self):
        self.user1 = create_random_authenticated_user("search_update_user")
        self.user2 = create_random_authenticated_user("search_update_other")
        self.paper1 = create_paper(title="paper1", uploaded_by=self.user1)
        self.paper2 = create_paper(title="paper2", uploaded_by=self.user2)
        self.post = ResearchhubPost.objects.create(
            created_by=self.user1,
            title="User Post",
            renderable_text="User post content",
            document_type="DISCUSSION",
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type="DISCUSSION"
            ),
        )
        self.other_post = ResearchhubPost.objects.create(
            created_by=self.user2,
            title="Other Post",
            renderable_text="Other post content",
            document_type="DISCUSSION",
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type="DISCUSSION"
            ),
        )

    @patch("search.tasks.PersonDocument.update")
    @patch("search.tasks.UserDocument.update")
    @patch("search.tasks.PostDocument.update")
    @patch("search.tasks.PaperDocument.update")
    def test_update_user_related_documents(
        self,
        paper_update_mock: Mock,
        post_update_mock: Mock,
        user_update_mock: Mock,
        person_update_mock: Mock,
    ):
        """
        Test that update_user_related_documents updates the documents
        for the given user.
        """
        # Arrange
        user_id = self.user1.id

        # Act
        update_user_related_documents(user_id)

        # Assert
        self.assertEqual(_get_updated_ids(paper_update_mock), [self.paper1.id])
        self.assertEqual(_get_updated_ids(post_update_mock), [self.post.id])
        self.assertEqual(_get_updated_ids(user_update_mock), [self.user1.id])
        self.assertEqual(
            _get_updated_ids(person_update_mock), [self.user1.author_profile.id]
        )

    @patch("search.tasks.PersonDocument.update")
    @patch("search.tasks.UserDocument.update")
    @patch("search.tasks.PostDocument.update")
    @patch("search.tasks.PaperDocument.update")
    def test_update_user_related_documents_missing_user(
        self,
        paper_update_mock: Mock,
        post_update_mock: Mock,
        user_update_mock: Mock,
        person_update_mock: Mock,
    ):
        """
        Test that update_user_related_documents does not attempt to update
        documents when the user does not exist.
        """
        # Arrange
        missing_user_id = -999999

        # Act
        update_user_related_documents(missing_user_id)

        # Assert
        paper_update_mock.assert_not_called()
        post_update_mock.assert_not_called()
        user_update_mock.assert_not_called()
        person_update_mock.assert_not_called()


def _get_updated_ids(mock_update: Mock) -> list[int]:
    return [obj.id for obj in mock_update.call_args[0][0]]
