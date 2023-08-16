from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from peer_review.models import PeerReviewRequest
from peer_review.related_models.peer_review_invite_model import PeerReviewInvite
from peer_review.tests.helpers import create_peer_review_request
from user.models import Organization, User
from user.tests.helpers import create_moderator, create_random_default_user


class PeerReviewRequestViewTests(APITestCase):
    def setUp(self):
        self.author = create_random_default_user("author")
        self.non_author = create_random_default_user("non_author")
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")

        self.hub = create_hub()
        self.client.force_authenticate(self.author)

        # Create org
        response = self.client.post("/api/organization/", {"name": "test org"})
        self.org = response.data

        # Create Note
        note_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        self.note = note_response.data

        # Create Note version
        note_version_response = self.client.post(
            "/api/note_content/",
            {
                "full_src": "test content",
                "note": self.note["id"],
                "plain_text": "test content",
            },
        )
        self.note_version = note_version_response.data

        # Author Publish
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "full_src": "body",
                "renderable_text": "body",
                "title": "title",
                "note_id": self.note["id"],
                "hubs": [self.hub.id],
                "authors": [self.author.author_profile.id],
            },
        )

        self.post = doc_response.data

    def test_author_can_request_review(self):
        self.client.force_authenticate(self.author)

        review_request_response = self.client.post(
            "/api/peer_review_requests/request_review/",
            {
                "unified_document": self.post["unified_document_id"],
                "doc_version": self.post["note"]["latest_version"]["id"],
            },
        )

        self.assertIn("id", review_request_response.data)

    def test_author_can_request_review_when_publishing(self):
        self.client.force_authenticate(self.author)

        # Create Note
        note_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = note_response.data

        # Create Note version
        note_version_response = self.client.post(
            "/api/note_content/",
            {
                "full_src": "test content",
                "note": note["id"],
                "plain_text": "test content",
            },
        )

        # Publish + Request review
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": self.author.id,
                "full_src": "body",
                "renderable_text": "body",
                "title": "title",
                "note_id": note["id"],
                "hubs": [self.hub.id],
                "request_peer_review": True,
            },
        )

        p = PeerReviewRequest.objects.get(
            unified_document=doc_response.data["unified_document_id"]
        )
        self.assertEqual(
            doc_response.data["unified_document_id"], p.unified_document_id
        )

    def test_NON_AUTHOR_cannot_request_review(self):
        self.client.force_authenticate(self.non_author)

        review_request_response = self.client.post(
            "/api/peer_review_requests/request_review/",
            {
                "unified_document": self.post["unified_document_id"],
                "doc_version": self.post["note"]["latest_version"]["id"],
            },
        )

        self.assertEqual(403, review_request_response.status_code)

    def test_moderator_can_request_review(self):
        self.client.force_authenticate(self.moderator)

        review_request_response = self.client.post(
            "/api/peer_review_requests/request_review/",
            {
                "unified_document": self.post["unified_document_id"],
                "doc_version": self.post["note"]["latest_version"]["id"],
            },
        )

        self.assertIn("id", review_request_response.data)

    def test_MODERATOR_can_view_all_review_requests(self):
        self.user1 = create_random_default_user("regular_user")
        self.user2 = create_random_default_user("regular_user2")

        review_request_for_user1 = create_peer_review_request(
            requested_by_user=self.user1,
            organization=Organization.objects.get(id=self.org["id"]),
            title="Some random post title",
            body="some text",
        )
        review_request_for_user2 = create_peer_review_request(
            requested_by_user=self.user2,
            organization=Organization.objects.get(id=self.org["id"]),
            title="Some random post title",
            body="some text",
        )

        self.client.force_authenticate(self.moderator)
        review_request_response = self.client.get("/api/peer_review_requests/")
        self.assertEqual(review_request_response.data["count"], 2)

    def test_author_can_review_own_requests(self):
        self.user1 = create_random_default_user("regular_user")
        self.user2 = create_random_default_user("regular_user2")

        review_request_for_user1 = create_peer_review_request(
            requested_by_user=self.user1,
            organization=Organization.objects.get(id=self.org["id"]),
            title="Some random post title",
            body="some text",
        )
        review_request_for_user2 = create_peer_review_request(
            requested_by_user=self.user2,
            organization=Organization.objects.get(id=self.org["id"]),
            title="Some random post title",
            body="some text",
        )

        self.client.force_authenticate(self.user1)
        review_request_response = self.client.get("/api/peer_review_requests/")
        self.assertEqual(review_request_response.data["count"], 1)

    def test_moderators_can_view_peer_review_request_details(self):
        author = create_random_default_user("regular_user")
        user = create_random_default_user("random_user")
        peer_reviewer = create_random_default_user("peer_reviewer")

        # Create review
        review_request_for_author = create_peer_review_request(
            requested_by_user=author,
            organization=Organization.objects.get(id=self.org["id"]),
            title="Some random post title",
            body="some text",
        )

        # Invite user
        self.client.force_authenticate(self.moderator)
        invite_response = self.client.post(
            "/api/peer_review_invites/invite/",
            {
                "recipient": peer_reviewer.id,
                "peer_review_request": review_request_for_author.id,
            },
        )

        # Decline invite
        self.client.force_authenticate(user)
        response = self.client.post(
            f'/api/peer_review_invites/{invite_response.data["id"]}/decline/'
        )

        # Retrieve request + details
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            f"/api/peer_review_requests/{review_request_for_author.id}/"
        )

        self.assertEqual(response.data["invites"][0]["id"], invite_response.data["id"])

    def test_authors_cannot_view_peer_review_request_details(self):
        author = create_random_default_user("regular_user")
        user = create_random_default_user("random_user")
        peer_reviewer = create_random_default_user("peer_reviewer")

        # Create review
        review_request_for_author = create_peer_review_request(
            requested_by_user=author,
            organization=Organization.objects.get(id=self.org["id"]),
            title="Some random post title",
            body="some text",
        )

        # Invite user
        self.client.force_authenticate(self.moderator)
        invite_response = self.client.post(
            "/api/peer_review_invites/invite/",
            {
                "recipient": peer_reviewer.id,
                "peer_review_request": review_request_for_author.id,
            },
        )

        # Decline invite
        self.client.force_authenticate(user)
        response = self.client.post(
            f'/api/peer_review_invites/{invite_response.data["id"]}/decline/'
        )

        # Retrieve request + details
        self.client.force_authenticate(self.author)
        response = self.client.get(
            f"/api/peer_review_requests/{review_request_for_author.id}/"
        )

        self.assertEqual(response.status_code, 403)

    def test_listing_requests_returns_invites(self):
        author = create_random_default_user("regular_user")
        user = create_random_default_user("random_user")
        peer_reviewer = create_random_default_user("peer_reviewer")

        # Create review request
        review_request_for_author = create_peer_review_request(
            requested_by_user=author,
            organization=Organization.objects.get(id=self.org["id"]),
            title="Some random post title",
            body="some text",
        )

        # Invite user
        self.client.force_authenticate(self.moderator)
        invite_response = self.client.post(
            "/api/peer_review_invites/invite/",
            {
                "recipient": peer_reviewer.id,
                "peer_review_request": review_request_for_author.id,
            },
        )

        # Fetch list
        list_response = self.client.get("/api/peer_review_requests/")

        self.assertEqual(len(list_response.data["results"][0]["invites"]), 1)
