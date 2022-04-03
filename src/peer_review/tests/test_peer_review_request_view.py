from rest_framework.test import APITestCase

class PeerReviewRequestViewTests(APITestCase):
    def test_author_can_request_review(self):
        self.assertEqual(False, True)

    def test_non_author_cannot_request_review(self):
        self.assertEqual(False, True)

    def test_moderator_can_request_review(self):
        self.assertEqual(False, True)

    def test_moderator_can_invite_reviewers(self):
        self.assertEqual(False, True)

    def test_moderator_can_invite_reviewers(self):
        self.assertEqual(False, True)

    def test_invited_reviewer_accept(self):
        self.assertEqual(False, True)

    def test_invited_reviewer_declines(self):
        self.assertEqual(False, True)

    def test_user_not_invited_cannot_accept(self):
        self.assertEqual(False, True)

    def test_user_not_invited_cannot_decline(self):
        self.assertEqual(False, True)