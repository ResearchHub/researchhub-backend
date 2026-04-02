from unittest.mock import MagicMock

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase

from ai_peer_review.services.report_access import (
    is_editor_or_moderator,
    user_can_view_grant_comparison,
    user_can_view_proposal_review,
)


class ReportAccessHelpersTests(SimpleTestCase):
    def test_is_editor_or_moderator_anonymous(self):
        self.assertFalse(is_editor_or_moderator(AnonymousUser()))

    def test_is_editor_or_moderator_moderator(self):
        user = MagicMock()
        user.is_authenticated = True
        user.moderator = True
        self.assertTrue(is_editor_or_moderator(user))

    def test_is_editor_or_moderator_hub_editor(self):
        user = MagicMock()
        user.is_authenticated = True
        user.moderator = False
        user.is_hub_editor = MagicMock(return_value=True)
        self.assertTrue(is_editor_or_moderator(user))

    def test_is_editor_or_moderator_plain_user(self):
        user = MagicMock()
        user.is_authenticated = True
        user.moderator = False
        user.is_hub_editor = MagicMock(return_value=False)
        self.assertFalse(is_editor_or_moderator(user))

    def test_user_can_view_proposal_review_anonymous(self):
        review = MagicMock()
        self.assertFalse(user_can_view_proposal_review(AnonymousUser(), review))

    def test_user_can_view_proposal_review_moderator(self):
        user = MagicMock()
        user.is_authenticated = True
        user.moderator = True
        review = MagicMock()
        self.assertTrue(user_can_view_proposal_review(user, review))

    def test_user_can_view_proposal_review_owner(self):
        owner = MagicMock()
        owner.id = 10
        ud = MagicMock()
        ud.created_by = owner
        review = MagicMock()
        review.unified_document = ud
        review.grant_id = None

        user = MagicMock()
        user.is_authenticated = True
        user.moderator = False
        user.is_hub_editor = MagicMock(return_value=False)
        user.id = 10
        self.assertTrue(user_can_view_proposal_review(user, review))

    def test_user_can_view_proposal_review_grant_creator(self):
        grant = MagicMock()
        grant.created_by_id = 20
        review = MagicMock()
        review.unified_document = MagicMock(created_by=None)
        review.grant_id = 99
        review.grant = grant

        user = MagicMock()
        user.is_authenticated = True
        user.moderator = False
        user.is_hub_editor = MagicMock(return_value=False)
        user.id = 20
        self.assertTrue(user_can_view_proposal_review(user, review))

    def test_user_can_view_grant_comparison_anonymous(self):
        grant = MagicMock()
        self.assertFalse(user_can_view_grant_comparison(AnonymousUser(), grant))

    def test_user_can_view_grant_comparison_funder(self):
        grant = MagicMock()
        grant.created_by_id = 7
        user = MagicMock()
        user.is_authenticated = True
        user.moderator = False
        user.is_hub_editor = MagicMock(return_value=False)
        user.id = 7
        self.assertTrue(user_can_view_grant_comparison(user, grant))

    def test_user_can_view_grant_comparison_stranger(self):
        grant = MagicMock()
        grant.created_by_id = 1
        user = MagicMock()
        user.is_authenticated = True
        user.moderator = False
        user.is_hub_editor = MagicMock(return_value=False)
        user.id = 2
        self.assertFalse(user_can_view_grant_comparison(user, grant))
