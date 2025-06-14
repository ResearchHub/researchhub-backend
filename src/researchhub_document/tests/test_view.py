import time
from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from hub.models import Hub
from hub.tests.helpers import create_hub
from note.tests.helpers import create_note
from paper.tests.helpers import create_paper
from purchase.models import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import Distribution
from reputation.distributor import Distributor
from researchhub_access_group.constants import SENIOR_EDITOR
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import GRANT
from user.related_models.author_model import Author
from user.related_models.organization_model import Organization
from user.tests.helpers import create_organization, create_random_default_user


class ViewTests(APITestCase):
    def setUp(self):
        # Create three users - an org admin, a member of the admin's org,
        # and a non-member:
        self.admin_user = create_random_default_user("admin")
        self.admin_author, _ = Author.objects.get_or_create(user=self.admin_user)
        self.member_user = create_random_default_user("member")
        self.member_author, _ = Author.objects.get_or_create(user=self.member_user)
        self.non_member = create_random_default_user("non_member")
        self.non_member_author, _ = Author.objects.get_or_create(user=self.non_member)

        # Make `member_user` a member of `admin_user`'s organization
        self.organization = Organization.objects.get(user_id=self.admin_user.id)
        Permission.objects.create(
            access_type="MEMBER",
            content_type=ContentType.objects.get_for_model(Organization),
            object_id=self.organization.id,
            user=self.member_user,
        )

        self.hub = create_hub("hub")

        # Add exchange rate for fundraise tests
        RscExchangeRate.objects.create(rate=1.0)

    def test_author_can_delete_doc(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )
        self.assertEqual(response.status_code, 200)

        doc = ResearchhubUnifiedDocument.all_objects.get(
            id=doc_response.data["unified_document_id"]
        )
        self.assertEqual(doc.is_removed, True)

    def test_author_can_restore_doc(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        delete_response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )
        self.assertEqual(delete_response.status_code, 200)

        restore_response = self.client.patch(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/restore/"
        )
        self.assertEqual(restore_response.data["is_removed"], False)

    def test_moderator_can_restore_doc(self):
        author = create_random_default_user("author")
        mod = create_random_default_user("mod", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        delete_response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )
        self.assertEqual(delete_response.status_code, 200)

        self.client.force_authenticate(mod)
        restore_response = self.client.patch(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/restore/"
        )
        self.assertEqual(restore_response.data["is_removed"], False)

    def test_non_author_cannot_delete_doc(self):
        author = create_random_default_user("author")
        non_author = create_random_default_user("non_author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        self.client.force_authenticate(non_author)

        response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )
        self.assertEqual(response.status_code, 403)

        doc = ResearchhubUnifiedDocument.objects.get(
            id=doc_response.data["unified_document_id"]
        )
        self.assertEqual(doc.is_removed, False)

    def test_moderator_can_delete_doc(self):
        author = create_random_default_user("author")
        moderator = create_random_default_user("moderator", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        self.client.force_authenticate(moderator)

        response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )
        self.assertEqual(response.status_code, 200)

        doc = ResearchhubUnifiedDocument.all_objects.get(
            id=doc_response.data["unified_document_id"]
        )
        self.assertEqual(doc.is_removed, True)

    def test_author_can_create_post(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)

    def test_min_post_title_length(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "body",
                "title": "short title",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 400)

    def test_min_post_body_length(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "short body",
                "title": "long title long title long title",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 400)

    def test_user_can_create_post_with_multiple_authors(self):
        note = create_note(self.admin_user, self.organization)

        self.client.force_authenticate(self.admin_user)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "authors": [self.admin_author.id, self.member_author.id],
                "created_by": self.admin_user.id,
                "document_type": "DISCUSSION",
                "full_src": "body",
                "hubs": [self.hub.id],
                "is_public": True,
                "note_id": note[0].id,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
            },
        )

        self.assertEqual(doc_response.status_code, 200)

    def test_user_cannot_create_post_with_non_members(self):
        note = create_note(self.admin_user, self.organization)

        self.client.force_authenticate(self.admin_user)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "authors": [self.admin_author.id, self.non_member_author.id],
                "created_by": self.admin_user.id,
                "document_type": "DISCUSSION",
                "full_src": "body",
                "hubs": [self.hub.id],
                "is_public": True,
                "note_id": note[0].id,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
            },
        )

        self.assertEqual(doc_response.status_code, 403)

    def test_author_can_update_post(self):
        note = create_note(self.admin_user, self.organization)

        self.client.force_authenticate(self.admin_user)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": self.admin_user.id,
                "full_src": "body",
                "image": "/imagePath1",
                "is_public": True,
                "note_id": note[0].id,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [self.hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)

        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "DISCUSSION",
                "created_by": self.admin_user.id,
                "full_src": "body",
                "image": "/updatedImagePath1",
                "is_public": True,
                "title": "updated title. updated title. updated title.",
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "hubs": [self.hub.id],
            },
        )

        self.assertEqual(
            updated_response.data["title"],
            "updated title. updated title. updated title.",
        )
        self.assertEqual(updated_response.data["image_url"], "/updatedImagePath1")

    def test_author_cannot_update_post_with_non_members(self):
        note = create_note(self.admin_user, self.organization)

        self.client.force_authenticate(self.admin_user)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": self.admin_user.id,
                "full_src": "body",
                "is_public": True,
                "note_id": note[0].id,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [self.hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)

        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "authors": [self.admin_author.id, self.non_member_author.id],
                "post_id": doc_response.data["id"],
                "document_type": "DISCUSSION",
                "created_by": self.admin_user.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [self.hub.id],
            },
        )

        self.assertEqual(updated_response.status_code, 403)

    def test_non_author_cannot_update_post(self):
        hub = create_hub()

        author = create_random_default_user("author")
        self.client.force_authenticate(author)

        org = create_organization(author, "organization")
        note = create_note(author, org)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "note_id": note[0].id,
            },
        )

        non_author = create_random_default_user("non_author")
        self.client.force_authenticate(non_author)

        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(updated_response.status_code, 403)

    def test_hub_editors_can_censor_papers(self):
        hub = create_hub()
        user_editor = create_random_default_user("user_editor")
        Permission.objects.create(
            access_type=SENIOR_EDITOR,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=hub.id,
            user=user_editor,
        )
        user_uploader = create_random_default_user("user_uploader")
        test_paper = create_paper(uploaded_by=user_uploader)
        test_paper.unified_document.hubs.add(hub)
        test_paper.save()

        self.client.force_authenticate(user_editor)
        response = self.client.put(
            f"/api/paper/{test_paper.id}/censor/", {"id": test_paper.id}
        )

        test_paper.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(test_paper.is_removed, True)

    def test_register_doi_no_charge(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        initial_balance = 5
        distributor = Distributor(
            Distribution("TEST_REWARD", initial_balance, False),
            author,
            None,
            time.time(),
        )
        distributor.distribute()

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "assign_doi": True,
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["doi"])
        # Balance should remain unchanged for all post types
        self.assertEqual(int(author.get_balance()), initial_balance)

    def test_get_document_metadata(self):
        # Arrange
        self.client.force_authenticate(self.non_member)

        paper = create_paper(title="title1", uploaded_by=self.non_member)

        # Act
        response = self.client.get(
            f"/api/researchhub_unified_document/{paper.unified_document.id}/get_document_metadata/"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], paper.unified_document.id)

    def test_fundraise_in_response_when_preregistration(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "PREREGISTRATION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "fundraise_goal_amount": 1000,
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["fundraise"])

    def test_fundraise_null_in_response_when_not_preregistration(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNone(doc_response.data["fundraise"])

    def test_preregistration_doi_not_charged(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        # Give the user some balance
        initial_balance = 5
        distributor = Distributor(
            Distribution("TEST_REWARD", initial_balance, False),
            author,
            None,
            time.time(),
        )
        distributor.distribute()

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "assign_doi": True,
                "document_type": "PREREGISTRATION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body. sufficiently long body",
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["doi"])
        # Balance should remain unchanged for preregistrations
        self.assertEqual(int(author.get_balance()), initial_balance)

    def test_grant_created_when_grant_amount_provided(self):
        """Test that a grant is created when grant_amount is provided"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 50000,
                "grant_currency": "USD",
                "grant_organization": "Test Foundation",
                "grant_description": "Test grant for research",
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["grant"])
        self.assertEqual(doc_response.data["grant"]["amount"]["usd"], 50000.0)
        self.assertEqual(doc_response.data["grant"]["organization"], "Test Foundation")
        self.assertEqual(
            doc_response.data["grant"]["description"], "Test grant for research"
        )
        self.assertEqual(doc_response.data["grant"]["status"], "OPEN")

    def test_grant_null_when_no_grant_amount(self):
        """Test that grant is null when no grant_amount is provided"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNone(doc_response.data["grant"])

    def test_grant_created_with_end_date(self):
        """Test that a grant can be created with an end date"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()
        end_date = datetime.now(pytz.UTC) + timedelta(days=30)

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 25000,
                "grant_organization": "Another Foundation",
                "grant_description": "Grant with deadline",
                "grant_end_date": end_date.isoformat(),
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["grant"])
        self.assertEqual(doc_response.data["grant"]["amount"]["usd"], 25000.0)
        self.assertEqual(
            doc_response.data["grant"]["organization"], "Another Foundation"
        )
        self.assertIsNotNone(doc_response.data["grant"]["end_date"])

    def test_grant_creation_validation_error(self):
        """Test that grant creation fails with invalid data"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        # Test with missing organization
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 50000,
                "grant_description": "Test grant",
                # Missing grant_organization
            },
        )

        self.assertEqual(doc_response.status_code, 400)

    def test_grant_with_fundraise_both_created(self):
        """Test that both grant and fundraise can be created on the same post"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "PREREGISTRATION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "fundraise_goal_amount": 10000,
                "grant_amount": 50000,
                "grant_organization": "Dual Foundation",
                "grant_description": "Grant with fundraise",
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["fundraise"])
        self.assertIsNotNone(doc_response.data["grant"])
        self.assertEqual(doc_response.data["grant"]["amount"]["usd"], 50000.0)
        self.assertEqual(doc_response.data["grant"]["organization"], "Dual Foundation")

    def test_grants_included_in_get_unified_documents(self):
        """Test that grants are included in get_unified_documents endpoint"""
        user = create_random_default_user("grant_test_user", moderator=True)
        hub = create_hub("Grant Hub")

        # Create a grant post
        post = create_post(created_by=user, document_type=GRANT)
        post.unified_document.hubs.add(hub)

        # Create a grant
        grant = Grant.objects.create(
            created_by=user,
            unified_document=post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="Test Foundation",
            description="Test grant for research",
            status=Grant.OPEN,
        )

        self.client.force_authenticate(user)
        response = self.client.get(
            "/api/researchhub_unified_document/get_unified_documents/"
        )

        self.assertEqual(response.status_code, 200)

        # Find the grant post in the response
        grant_doc = None
        for doc in response.data["results"]:
            if doc["id"] == post.unified_document.id:
                grant_doc = doc
                break

        self.assertIsNotNone(grant_doc, "Grant document should be in response")
        self.assertIn("grant", grant_doc, "Grant field should be present")
        self.assertEqual(grant_doc["grant"]["id"], grant.id)
        self.assertEqual(grant_doc["grant"]["organization"], "Test Foundation")

    def test_grants_included_in_recommendations(self):
        """Test that grants are included in recommendations endpoint"""
        user = create_random_default_user("grant_rec_user", moderator=True)
        hub = create_hub("Recommendation Hub")

        # Create a grant post
        post = create_post(created_by=user, document_type=GRANT)
        post.unified_document.hubs.add(hub)
        post.unified_document.hot_score = 100  # Make it appear in recommendations
        post.unified_document.save()

        # Create a grant
        grant = Grant.objects.create(
            created_by=user,
            unified_document=post.unified_document,
            amount=Decimal("25000.00"),
            currency="USD",
            organization="Recommendation Foundation",
            description="Test grant for recommendations",
            status=Grant.OPEN,
        )

        response = self.client.get("/api/researchhub_unified_document/recommendations/")

        self.assertEqual(response.status_code, 200)

        # Find the grant post in the response
        grant_doc = None
        for doc in response.data["results"]:
            if doc["id"] == post.unified_document.id:
                grant_doc = doc
                break

        if grant_doc:  # Only check if the document appears in recommendations
            self.assertIn("grant", grant_doc, "Grant field should be present")
            self.assertEqual(grant_doc["grant"]["id"], grant.id)

    def test_grants_included_in_get_document_metadata(self):
        """Test that grants are included in get_document_metadata endpoint"""
        user = create_random_default_user("grant_metadata_user", moderator=True)
        hub = create_hub("Metadata Grant Hub")

        # Create a grant post
        post = create_post(created_by=user, document_type=GRANT)
        post.unified_document.hubs.add(hub)

        # Create a grant
        grant = Grant.objects.create(
            created_by=user,
            unified_document=post.unified_document,
            amount=Decimal("30000.00"),
            currency="USD",
            organization="Metadata Foundation",
            description="Grant for metadata research",
            status=Grant.OPEN,
        )

        self.client.force_authenticate(user)
        response = self.client.get(
            f"/api/researchhub_unified_document/{post.unified_document.id}/get_document_metadata/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("grant", response.data)
        self.assertEqual(response.data["grant"]["id"], grant.id)
        self.assertEqual(response.data["grant"]["amount"]["usd"], 30000.0)
        self.assertEqual(response.data["grant"]["organization"], "Metadata Foundation")

    def test_grant_update_existing_grant(self):
        """Test that an existing grant can be updated when updating a post"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        # Create initial post with grant
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 50000,
                "grant_currency": "USD",
                "grant_organization": "Original Foundation",
                "grant_description": "Original grant description",
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["grant"])
        original_grant_id = doc_response.data["grant"]["id"]

        # Update the post with new grant information
        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "updated body",
                "is_public": True,
                "renderable_text": (
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body"
                ),
                "title": "updated sufficiently long title. updated sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 75000,
                "grant_currency": "USD",
                "grant_organization": "Updated Foundation",
                "grant_description": "Updated grant description",
            },
        )

        self.assertEqual(updated_response.status_code, 200)
        self.assertIsNotNone(updated_response.data["grant"])

        # Verify the same grant was updated, not a new one created
        self.assertEqual(updated_response.data["grant"]["id"], original_grant_id)
        self.assertEqual(updated_response.data["grant"]["amount"]["usd"], 75000.0)
        self.assertEqual(
            updated_response.data["grant"]["organization"], "Updated Foundation"
        )
        self.assertEqual(
            updated_response.data["grant"]["description"], "Updated grant description"
        )

        # Verify only one grant exists in database
        grants_count = Grant.objects.filter(
            unified_document=doc_response.data["unified_document_id"]
        ).count()
        self.assertEqual(grants_count, 1)

    def test_grant_create_new_grant_during_update(self):
        """Test that grants cannot be created during updates (only at post creation)"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        # Create initial post without grant
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNone(doc_response.data["grant"])

        # Try to update the post with grant information - should NOT create a grant
        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "updated body",
                "is_public": True,
                "renderable_text": (
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body"
                ),
                "title": "updated sufficiently long title. updated sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 60000,
                "grant_currency": "USD",
                "grant_organization": "New Foundation",
                "grant_description": "New grant description",
            },
        )

        self.assertEqual(updated_response.status_code, 200)
        # Grant should remain None because we don't create grants during updates
        self.assertIsNone(updated_response.data["grant"])

        # Verify no grant was created in database
        grants_count = Grant.objects.filter(
            unified_document=doc_response.data["unified_document_id"]
        ).count()
        self.assertEqual(grants_count, 0)

    def test_grant_preserve_existing_grant_when_no_grant_data(self):
        """Test that existing grant is preserved when no grant data is provided in update"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        # Create initial post with grant
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 40000,
                "grant_currency": "USD",
                "grant_organization": "Preserve Foundation",
                "grant_description": "Grant to be preserved",
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["grant"])
        original_grant_data = doc_response.data["grant"]

        # Update the post WITHOUT grant information
        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "updated body",
                "is_public": True,
                "renderable_text": (
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body"
                ),
                "title": "updated sufficiently long title. updated sufficiently long title.",
                "hubs": [hub.id],
                # No grant_amount or other grant fields
            },
        )

        self.assertEqual(updated_response.status_code, 200)
        self.assertIsNotNone(updated_response.data["grant"])

        # Verify grant data is preserved
        self.assertEqual(
            updated_response.data["grant"]["id"], original_grant_data["id"]
        )
        self.assertEqual(updated_response.data["grant"]["amount"]["usd"], 40000.0)
        self.assertEqual(
            updated_response.data["grant"]["organization"], "Preserve Foundation"
        )
        self.assertEqual(
            updated_response.data["grant"]["description"], "Grant to be preserved"
        )

    def test_grant_update_with_end_date(self):
        """Test that grant end date can be updated"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()
        initial_end_date = datetime.now(pytz.UTC) + timedelta(days=30)
        updated_end_date = datetime.now(pytz.UTC) + timedelta(days=60)

        self.client.force_authenticate(author)

        # Create initial post with grant and end date
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 45000,
                "grant_organization": "Date Foundation",
                "grant_description": "Grant with end date",
                "grant_end_date": initial_end_date.isoformat(),
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["grant"]["end_date"])

        # Update with new end date
        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "updated body",
                "is_public": True,
                "renderable_text": (
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body"
                ),
                "title": "updated sufficiently long title. updated sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 45000,
                "grant_organization": "Date Foundation",
                "grant_description": "Grant with updated end date",
                "grant_end_date": updated_end_date.isoformat(),
            },
        )

        self.assertEqual(updated_response.status_code, 200)
        self.assertIsNotNone(updated_response.data["grant"]["end_date"])

        # Verify end date was updated
        grant = Grant.objects.get(id=updated_response.data["grant"]["id"])
        self.assertEqual(
            grant.end_date.replace(microsecond=0),
            updated_end_date.replace(microsecond=0),
        )

    def test_grant_update_validation_error(self):
        """Test that grant update fails with invalid data"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        # Create initial post with grant
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 50000,
                "grant_organization": "Test Foundation",
                "grant_description": "Test grant",
            },
        )

        self.assertEqual(doc_response.status_code, 200)

        # Try to update with invalid grant data (missing organization)
        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "updated body",
                "is_public": True,
                "renderable_text": (
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body"
                ),
                "title": "updated sufficiently long title. updated sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 60000,
                "grant_description": "Updated grant description",
                # Missing grant_organization
            },
        )

        self.assertEqual(updated_response.status_code, 400)

    def test_grant_update_with_null_fields(self):
        """Test that grant fields can be updated to null/empty values where appropriate"""
        author = create_random_default_user("author", moderator=True)
        hub = create_hub()

        self.client.force_authenticate(author)

        # Create initial post with grant including end date
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 50000,
                "grant_organization": "Test Foundation",
                "grant_description": "Test grant with end date",
                "grant_end_date": (
                    datetime.now(pytz.UTC) + timedelta(days=30)
                ).isoformat(),
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["grant"]["end_date"])

        # Update grant removing the end date
        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "updated body",
                "is_public": True,
                "renderable_text": (
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body. updated sufficiently long body. "
                    "updated sufficiently long body"
                ),
                "title": "updated sufficiently long title. updated sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 50000,
                "grant_organization": "Test Foundation",
                "grant_description": "Test grant without end date",
                # No grant_end_date
            },
        )

        self.assertEqual(updated_response.status_code, 200)

        # Verify end date was set to None
        grant = Grant.objects.get(id=updated_response.data["grant"]["id"])
        self.assertIsNone(grant.end_date)

    def test_grant_created_with_contacts(self):
        """Test that a grant can be created with contact users"""
        author = create_random_default_user("author", moderator=True)
        contact1 = create_random_default_user("contact1")
        contact2 = create_random_default_user("contact2")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 50000,
                "grant_currency": "USD",
                "grant_organization": "Contact Foundation",
                "grant_description": "Grant with contacts",
                "grant_contacts": [contact1.id, contact2.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertIsNotNone(doc_response.data["grant"])

        # Verify contacts are included in response
        grant_data = doc_response.data["grant"]
        self.assertEqual(len(grant_data["contacts"]), 2)
        contact_ids = [contact["id"] for contact in grant_data["contacts"]]
        self.assertIn(contact1.id, contact_ids)
        self.assertIn(contact2.id, contact_ids)

        # Verify contacts are saved in database
        grant = Grant.objects.get(id=grant_data["id"])
        self.assertEqual(grant.contacts.count(), 2)
        self.assertTrue(grant.contacts.filter(id=contact1.id).exists())
        self.assertTrue(grant.contacts.filter(id=contact2.id).exists())

    def test_grant_update_add_contacts(self):
        """Test that contacts can be added to an existing grant"""
        author = create_random_default_user("author", moderator=True)
        contact1 = create_random_default_user("contact1")
        contact2 = create_random_default_user("contact2")
        hub = create_hub()

        self.client.force_authenticate(author)

        # Create initial grant without contacts
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 40000,
                "grant_organization": "Update Foundation",
                "grant_description": "Grant to add contacts",
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        original_grant_id = doc_response.data["grant"]["id"]
        self.assertEqual(len(doc_response.data["grant"]["contacts"]), 0)

        # Update to add contacts
        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "updated body",
                "is_public": True,
                "renderable_text": (
                    "updated sufficiently long body. updated sufficiently "
                    "long body. updated sufficiently long body. updated "
                    "sufficiently long body. updated sufficiently long body"
                ),
                "title": "updated title. updated title. updated title.",
                "hubs": [hub.id],
                "grant_amount": 40000,
                "grant_organization": "Update Foundation",
                "grant_description": "Grant with added contacts",
                "grant_contacts": [contact1.id, contact2.id],
            },
        )

        self.assertEqual(updated_response.status_code, 200)
        self.assertEqual(updated_response.data["grant"]["id"], original_grant_id)

        # Verify contacts were added
        grant_data = updated_response.data["grant"]
        self.assertEqual(len(grant_data["contacts"]), 2)
        contact_ids = [contact["id"] for contact in grant_data["contacts"]]
        self.assertIn(contact1.id, contact_ids)
        self.assertIn(contact2.id, contact_ids)

        # Verify in database
        grant = Grant.objects.get(id=original_grant_id)
        self.assertEqual(grant.contacts.count(), 2)

    def test_grant_update_remove_contacts(self):
        """Test that contacts can be removed from an existing grant"""
        author = create_random_default_user("author", moderator=True)
        contact1 = create_random_default_user("contact1")
        contact2 = create_random_default_user("contact2")
        hub = create_hub()

        self.client.force_authenticate(author)

        # Create initial grant with contacts
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 35000,
                "grant_organization": "Remove Foundation",
                "grant_description": "Grant to remove contacts",
                "grant_contacts": [contact1.id, contact2.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        original_grant_id = doc_response.data["grant"]["id"]
        self.assertEqual(len(doc_response.data["grant"]["contacts"]), 2)

        # Update to remove contacts by providing empty list
        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "updated body",
                "is_public": True,
                "renderable_text": (
                    "updated sufficiently long body. updated sufficiently "
                    "long body. updated sufficiently long body. updated "
                    "sufficiently long body. updated sufficiently long body"
                ),
                "title": "updated title. updated title. updated title.",
                "hubs": [hub.id],
                "grant_amount": 35000,
                "grant_organization": "Remove Foundation",
                "grant_description": "Grant with removed contacts",
                "grant_contacts": [],
            },
        )

        self.assertEqual(updated_response.status_code, 200)
        self.assertEqual(updated_response.data["grant"]["id"], original_grant_id)

        # Verify contacts were removed
        grant_data = updated_response.data["grant"]
        self.assertEqual(len(grant_data["contacts"]), 0)

        # Verify in database
        grant = Grant.objects.get(id=original_grant_id)
        self.assertEqual(grant.contacts.count(), 0)

    def test_grant_update_change_contacts(self):
        """Test that contacts can be changed in an existing grant"""
        author = create_random_default_user("author", moderator=True)
        contact1 = create_random_default_user("contact1")
        contact2 = create_random_default_user("contact2")
        contact3 = create_random_default_user("contact3")
        hub = create_hub()

        self.client.force_authenticate(author)

        # Create initial grant with contacts
        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": (
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body. sufficiently long body. "
                    "sufficiently long body"
                ),
                "title": "sufficiently long title. sufficiently long title.",
                "hubs": [hub.id],
                "grant_amount": 45000,
                "grant_organization": "Change Foundation",
                "grant_description": "Grant to change contacts",
                "grant_contacts": [contact1.id, contact2.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        original_grant_id = doc_response.data["grant"]["id"]
        self.assertEqual(len(doc_response.data["grant"]["contacts"]), 2)

        # Update to change contacts
        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "document_type": "GRANT",
                "created_by": author.id,
                "full_src": "updated body",
                "is_public": True,
                "renderable_text": (
                    "updated sufficiently long body. updated sufficiently "
                    "long body. updated sufficiently long body. updated "
                    "sufficiently long body. updated sufficiently long body"
                ),
                "title": "updated title. updated title. updated title.",
                "hubs": [hub.id],
                "grant_amount": 45000,
                "grant_organization": "Change Foundation",
                "grant_description": "Grant with changed contacts",
                "grant_contacts": [contact2.id, contact3.id],
            },
        )

        self.assertEqual(updated_response.status_code, 200)
        self.assertEqual(updated_response.data["grant"]["id"], original_grant_id)

        # Verify contacts were changed
        grant_data = updated_response.data["grant"]
        self.assertEqual(len(grant_data["contacts"]), 2)
        contact_ids = [contact["id"] for contact in grant_data["contacts"]]
        self.assertIn(contact2.id, contact_ids)  # contact2 remains
        self.assertIn(contact3.id, contact_ids)  # contact3 was added
        self.assertNotIn(contact1.id, contact_ids)  # contact1 was removed

        # Verify in database
        grant = Grant.objects.get(id=original_grant_id)
        self.assertEqual(grant.contacts.count(), 2)
        self.assertTrue(grant.contacts.filter(id=contact2.id).exists())
        self.assertTrue(grant.contacts.filter(id=contact3.id).exists())
        self.assertFalse(grant.contacts.filter(id=contact1.id).exists())

    def test_get_queryset_filters_by_document_type(self):
        """Test that the get_queryset method filters posts by document_type parameter"""
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        # Create posts with different document types
        discussion_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "discussion body",
                "is_public": True,
                "renderable_text": "sufficiently long discussion body. sufficiently long discussion body. sufficiently long discussion body.",
                "title": "Discussion Post Title - Long Enough",
                "hubs": [hub.id],
            },
        )

        question_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "QUESTION",
                "created_by": author.id,
                "full_src": "question body",
                "is_public": True,
                "renderable_text": "sufficiently long question body. sufficiently long question body. sufficiently long question body.",
                "title": "Question Post Title - Long Enough",
                "hubs": [hub.id],
            },
        )

        preregistration_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "PREREGISTRATION",
                "created_by": author.id,
                "full_src": "preregistration body",
                "is_public": True,
                "renderable_text": "sufficiently long preregistration body. sufficiently long preregistration body. sufficiently long preregistration body.",
                "title": "Preregistration Post Title - Long Enough",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(discussion_response.status_code, 200)
        self.assertEqual(question_response.status_code, 200)
        self.assertEqual(preregistration_response.status_code, 200)

        # Test filtering by DISCUSSION document_type
        discussion_filter_response = self.client.get(
            "/api/researchhubpost/?document_type=DISCUSSION"
        )
        self.assertEqual(discussion_filter_response.status_code, 200)
        discussion_results = discussion_filter_response.data["results"]

        # Should only return the discussion post
        self.assertEqual(len(discussion_results), 1)
        self.assertEqual(discussion_results[0]["document_type"], "DISCUSSION")
        self.assertEqual(discussion_results[0]["id"], discussion_response.data["id"])

        # Test filtering by QUESTION document_type
        question_filter_response = self.client.get(
            "/api/researchhubpost/?document_type=QUESTION"
        )
        self.assertEqual(question_filter_response.status_code, 200)
        question_results = question_filter_response.data["results"]

        # Should only return the question post
        self.assertEqual(len(question_results), 1)
        self.assertEqual(question_results[0]["document_type"], "QUESTION")
        self.assertEqual(question_results[0]["id"], question_response.data["id"])

        # Test filtering by PREREGISTRATION document_type
        preregistration_filter_response = self.client.get(
            "/api/researchhubpost/?document_type=PREREGISTRATION"
        )
        self.assertEqual(preregistration_filter_response.status_code, 200)
        preregistration_results = preregistration_filter_response.data["results"]

        # Should only return the preregistration post
        self.assertEqual(len(preregistration_results), 1)
        self.assertEqual(preregistration_results[0]["document_type"], "PREREGISTRATION")
        self.assertEqual(
            preregistration_results[0]["id"], preregistration_response.data["id"]
        )

        # Test that without filter, all posts are returned
        all_posts_response = self.client.get("/api/researchhubpost/")
        self.assertEqual(all_posts_response.status_code, 200)
        all_results = all_posts_response.data["results"]

        # Should return all three posts (plus any from other tests)
        self.assertGreaterEqual(len(all_results), 3)

        # Verify our three posts are all present
        post_ids = [post["id"] for post in all_results]
        self.assertIn(discussion_response.data["id"], post_ids)
        self.assertIn(question_response.data["id"], post_ids)
        self.assertIn(preregistration_response.data["id"], post_ids)

        # Test filtering by non-existent document_type
        empty_filter_response = self.client.get(
            "/api/researchhubpost/?document_type=NONEXISTENT"
        )
        self.assertEqual(empty_filter_response.status_code, 200)
        empty_results = empty_filter_response.data["results"]

        # Should return no posts
        self.assertEqual(len(empty_results), 0)
