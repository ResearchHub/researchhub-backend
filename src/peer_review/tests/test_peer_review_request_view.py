from rest_framework.test import APITestCase
from user.tests.helpers import (
    create_random_default_user,
    create_moderator,
)
from hub.tests.helpers import create_hub
from note.models import NoteContent


class PeerReviewRequestViewTests(APITestCase):
    def setUp(self):
        self.author = create_random_default_user('author')
        self.non_author = create_random_default_user('non_author')
        self.moderator = create_moderator(first_name='moderator', last_name='moderator')

        self.hub = create_hub()
        self.client.force_authenticate(self.author)

        # Create org
        response = self.client.post('/api/organization/', {'name': 'test org'})
        self.org = response.data

        # Create Note
        note_response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        self.note = note_response.data

        # Create Note version
        note_version_response = self.client.post(
            '/api/note_content/',
            {
                'full_src': 'test content',
                'note': self.note['id'],
                'plain_text': 'test content'
            }
        )
        self.note_version = note_version_response.data

        # Author Publish
        doc_response = self.client.post("/api/researchhub_posts/", {
            "document_type": "DISCUSSION",
            "created_by": self.author.id,
            "full_src": "body",
            "renderable_text": "body",
            "title": "title",
            "note_id": self.note['id'],
            "hubs": [self.hub.id],
        })
        self.post = doc_response.data


    def test_author_can_request_review(self):
        self.client.force_authenticate(self.author)

        review_request_response = self.client.post("/api/peer_review_requests/request_review/",{
            "unified_document": self.post['unified_document_id'],
            "doc_version": self.post['note']['latest_version']['id'],
        })

        self.assertIn('id', review_request_response.data)

    def test_non_author_cannot_request_review(self):
        self.client.force_authenticate(self.non_author)

        review_request_response = self.client.post("/api/peer_review_requests/request_review/",{
            "unified_document": self.post['unified_document_id'],
            "doc_version": self.post['note']['latest_version']['id'],
        })

        self.assertEqual(403, review_request_response.status_code)

    def test_moderator_can_request_review(self):
        self.client.force_authenticate(self.moderator)

        review_request_response = self.client.post("/api/peer_review_requests/request_review/",{
            "unified_document": self.post['unified_document_id'],
            "doc_version": self.post['note']['latest_version']['id'],
        })
        print(review_request_response)
        self.assertIn('id', review_request_response.data)

    # def test_moderator_can_invite_reviewers(self):
    #     self.assertEqual(False, True)

    # def test_moderator_can_invite_reviewers(self):
    #     self.assertEqual(False, True)

    # def test_invited_reviewer_accept(self):
    #     self.assertEqual(False, True)

    # def test_invited_reviewer_declines(self):
    #     self.assertEqual(False, True)

    # def test_user_not_invited_cannot_accept(self):
    #     self.assertEqual(False, True)

    # def test_user_not_invited_cannot_decline(self):
    #     self.assertEqual(False, True)