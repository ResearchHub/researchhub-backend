from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from purchase.models import Grant
from research_ai.permissions import (
    can_manage_grant,
    can_view_invited_experts_list,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_hub_editor, create_random_authenticated_user


class InvitedExpertsAccessTests(TestCase):
    def setUp(self):
        self.creator = create_random_authenticated_user("perm_creator")
        self.contact = create_random_authenticated_user("perm_contact")
        self.other = create_random_authenticated_user("perm_other")
        self.moderator = create_random_authenticated_user("perm_mod", moderator=True)
        post = create_post(created_by=self.creator, document_type=GRANT)
        self.grant = Grant.objects.create(
            created_by=self.creator,
            unified_document=post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Org",
            description="Desc",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )
        self.grant.contacts.add(self.contact)
        self.ud_id = post.unified_document_id

    def test_can_manage_grant_for_creator_contact_and_moderator(self):
        self.assertTrue(can_manage_grant(self.moderator, self.grant))
        self.assertTrue(can_manage_grant(self.creator, self.grant))
        self.assertTrue(can_manage_grant(self.contact, self.grant))
        self.assertFalse(can_manage_grant(self.other, self.grant))

    def test_can_view_invited_experts_list_for_grant_stakeholders(self):
        self.assertTrue(
            can_view_invited_experts_list(self.creator, unified_document_id=self.ud_id)
        )
        self.assertTrue(
            can_view_invited_experts_list(self.contact, unified_document_id=self.ud_id)
        )
        self.assertFalse(
            can_view_invited_experts_list(self.other, unified_document_id=self.ud_id)
        )

    def test_can_view_invited_experts_list_without_document_requires_editor(self):
        editor, _ = create_hub_editor("perm_editor", "perm_hub")
        self.assertTrue(
            can_view_invited_experts_list(self.moderator, unified_document_id=None)
        )
        self.assertTrue(can_view_invited_experts_list(editor, unified_document_id=None))
        self.assertFalse(
            can_view_invited_experts_list(self.creator, unified_document_id=None)
        )
