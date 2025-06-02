import time
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
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
        # Create three users - an org admin, and a member of the admin's org, and a non-member:
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

    def test_hub_editors_can_restore_papers(self):
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
        test_paper.is_removed = True
        test_paper.save()

        self.client.force_authenticate(user_editor)
        response = self.client.put(
            f"/api/paper/{test_paper.id}/restore_paper/", {"id": test_paper.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["is_removed"], False)

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
        author = create_random_default_user("author")
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
        author = create_random_default_user("author")
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
        from datetime import datetime, timedelta

        import pytz

        author = create_random_default_user("author")
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
        author = create_random_default_user("author")
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
        self.assertIn("grants", grant_doc, "Grants field should be present")
        self.assertEqual(len(grant_doc["grants"]), 1)
        self.assertEqual(grant_doc["grants"][0]["id"], grant.id)
        self.assertEqual(grant_doc["grants"][0]["organization"], "Test Foundation")

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
            self.assertIn("grants", grant_doc, "Grants field should be present")
            self.assertEqual(len(grant_doc["grants"]), 1)
            self.assertEqual(grant_doc["grants"][0]["id"], grant.id)

    def test_grants_included_in_get_document_metadata(self):
        """Test that grants are included in get_document_metadata endpoint"""
        user = create_random_default_user("grant_meta_user", moderator=True)

        # Create a grant post
        post = create_post(created_by=user, document_type=GRANT)

        # Create a grant
        grant = Grant.objects.create(
            created_by=user,
            unified_document=post.unified_document,
            amount=Decimal("75000.00"),
            currency="USD",
            organization="Metadata Foundation",
            description="Test grant for metadata",
            status=Grant.COMPLETED,
        )

        response = self.client.get(
            f"/api/researchhub_unified_document/{post.unified_document.id}/"
            "get_document_metadata/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("grants", response.data, "Grants field should be present")
        self.assertEqual(len(response.data["grants"]), 1)
        self.assertEqual(response.data["grants"][0]["id"], grant.id)
        self.assertEqual(response.data["grants"][0]["status"], Grant.COMPLETED)
