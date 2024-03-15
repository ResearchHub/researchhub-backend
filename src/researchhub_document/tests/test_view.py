import time

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from hub.models import Hub
from hub.tests.helpers import create_hub
from note.tests.helpers import create_note
from paper.tests.helpers import create_paper
from reputation.distributions import Distribution
from reputation.distributor import Distributor
from researchhub_access_group.constants import EDITOR
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from user.related_models.organization_model import Organization
from user.tests.helpers import create_organization, create_random_default_user


class ViewTests(APITestCase):
    def setUp(self):
        # Create three users - an org admin, and a member of the admin's org, and a non-member:
        self.admin_user = create_random_default_user("admin")
        self.member_user = create_random_default_user("member")
        self.non_member = create_random_default_user("non_member")

        # Make `member_user` a member of `admin_user`'s organization
        self.organization = Organization.objects.get(user_id=self.admin_user.id)
        Permission.objects.create(
            access_type="MEMBER",
            content_type=ContentType.objects.get_for_model(Organization),
            object_id=self.organization.id,
            user=self.member_user,
        )
        
        self.hub = create_hub("hub")

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
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )
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
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        delete_response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )
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
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        delete_response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )

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
            f"/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        self.client.force_authenticate(non_author)

        response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )
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
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        self.client.force_authenticate(moderator)

        response = self.client.delete(
            f"/api/researchhub_unified_document/{doc_response.data['unified_document_id']}/censor/"
        )
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
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)

    def test_user_can_create_post_with_multiple_authors(self):
        note = create_note(self.admin_user, self.organization)

        self.client.force_authenticate(self.admin_user)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "authors": [self.admin_user.id, self.member_user.id],
                "created_by": self.admin_user.id,
                "document_type": "DISCUSSION",
                "full_src": "body",
                "hubs": [self.hub.id],
                "is_public": True,
                "note_id": note[0].id,
                "renderable_text": "body",
                "title": "title",
            },
        )

        self.assertEqual(doc_response.status_code, 200)

    def test_user_cannot_create_post_with_non_members(self):
        note = create_note(self.admin_user, self.organization)

        self.client.force_authenticate(self.admin_user)

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "authors": [self.admin_user.id, self.non_member.id],
                "created_by": self.admin_user.id,
                "document_type": "DISCUSSION",
                "full_src": "body",
                "hubs": [self.hub.id],
                "is_public": True,
                "note_id": note[0].id,
                "renderable_text": "body",
                "title": "title",
            },
        )

        self.assertEqual(doc_response.status_code, 403)

    def test_author_can_update_post(self):
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
                "title": "title",
                "hubs": [hub.id],
            },
        )

        updated_response = self.client.post(
            "/api/researchhubpost/",
            {
                "post_id": doc_response.data["id"],
                "title": "updated title",
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "body",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(updated_response.data["title"], "updated title")

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
                "renderable_text": "body",
                "title": "title",
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
                "title": "updated title",
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "body",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(updated_response.status_code, 403)

    def test_author_can_create_hypothesis(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/hypothesis/",
            {
                "document_type": "HYPOTHESIS",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "body",
                "title": "hypothesis",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)

    def test_author_can_update_hypothesis(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/hypothesis/",
            {
                "document_type": "HYPOTHESIS",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        updated_response = self.client.post(
            f"/api/hypothesis/{doc_response.data['id']}/upsert/",
            {
                "hypothesis_id": doc_response.data["id"],
                "title": "updated title",
                "document_type": "HYPOTHESIS",
                "full_src": "updated body",
                "renderable_text": "body",
            },
        )

        self.assertEqual(updated_response.data["full_markdown"], "updated body")

    def test_non_author_cannot_edit_hypothesis(self):
        author = create_random_default_user("author")
        non_author = create_random_default_user("non_author")
        hub = create_hub()

        self.client.force_authenticate(author)

        doc_response = self.client.post(
            "/api/hypothesis/",
            {
                "document_type": "HYPOTHESIS",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        self.client.force_authenticate(non_author)

        updated_response = self.client.post(
            f"/api/hypothesis/{doc_response.data['id']}/upsert/",
            {
                "hypothesis_id": doc_response.data["id"],
                "title": "updated title",
                "document_type": "HYPOTHESIS",
                "full_src": "updated body",
                "renderable_text": "body",
            },
        )
        self.assertEqual(updated_response.status_code, 403)

    def test_hub_editors_can_censor_papers(self):
        hub = create_hub()
        user_editor = create_random_default_user("user_editor")
        Permission.objects.create(
            access_type=EDITOR,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=hub.id,
            user=user_editor,
        )
        user_uploader = create_random_default_user("user_uploader")
        test_paper = create_paper(uploaded_by=user_uploader)
        test_paper.unified_document.hubs.add(hub)
        test_paper.hubs.add(hub)
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
            access_type=EDITOR,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=hub.id,
            user=user_editor,
        )
        user_uploader = create_random_default_user("user_uploader")
        test_paper = create_paper(uploaded_by=user_uploader)
        test_paper.hubs.add(hub)
        test_paper.is_removed = True
        test_paper.save()

        self.client.force_authenticate(user_editor)
        response = self.client.put(
            f"/api/paper/{test_paper.id}/restore_paper/", {"id": test_paper.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["is_removed"], False)

    def test_register_doi_with_sufficient_funds(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        distributor = Distributor(
            Distribution("TEST_REWARD", 5, False), author, None, time.time()
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
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertEqual(int(author.get_balance()), 0)

    def test_register_doi_with_insufficient_funds(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        distributor = Distributor(
            Distribution("TEST_REWARD", 4, False), author, None, time.time()
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
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 402)
        self.assertEqual(int(author.get_balance()), 4)

    def test_no_doi_with_sufficient_funds(self):
        author = create_random_default_user("author")
        hub = create_hub()

        self.client.force_authenticate(author)

        distributor = Distributor(
            Distribution("TEST_REWARD", 5, False), author, None, time.time()
        )
        distributor.distribute()

        doc_response = self.client.post(
            "/api/researchhubpost/",
            {
                "assign_doi": False,
                "document_type": "DISCUSSION",
                "created_by": author.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "body",
                "title": "title",
                "hubs": [hub.id],
            },
        )

        self.assertEqual(doc_response.status_code, 200)
        self.assertEqual(int(author.get_balance()), 5)
