import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from invite.related_models.note_invitation import NoteInvitation
from note.models import Note, NoteTemplate, PreregistrationSettings
from organizations.models import NonprofitOrg
from purchase.models import Fundraise, Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
from topic.models import Topic, UnifiedDocumentTopics
from user.models import Author, Organization
from user.tests.helpers import make_user_verified


class NoteTests(APITestCase):
    organization_ct = None
    unified_doc_ct = None

    def setUp(self):
        self.unified_doc_ct = ContentType.objects.get_for_model(
            ResearchhubUnifiedDocument
        )
        self.organization_ct = ContentType.objects.get_for_model(Organization)

        # Create + auth user
        username = "test@researchhub_test.com"
        password = uuid.uuid4().hex
        self.user = get_user_model().objects.create_user(
            username=username, password=password, email=username, moderator=True
        )
        make_user_verified(self.user)
        self.client.force_authenticate(self.user)

        # Create org
        response = self.client.post("/api/organization/", {"name": "some org"})
        self.org = response.data

        # Create exchange rate
        RscExchangeRate.objects.create(rate=4.99014625)

    def _create_grant(self, status: str = Grant.OPEN) -> Grant:
        """Create a grant visible to the authenticated moderator."""
        post = create_post(created_by=self.user, document_type=GRANT)
        return Grant.objects.create(
            created_by=self.user,
            unified_document=post.unified_document,
            amount=Decimal("1000.00"),
            description="Grant requirements",
            short_title="Kindness RFP",
            status=status,
        )

    def test_user_can_list_created_notes(self):
        # Arrange
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "title": "Test1",
            },
        )
        self.assertEqual(response.status_code, 200)

        # Act
        response = self.client.get("/api/note/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_user_cannot_list_other_users_notes(self):
        # Arrange
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "title": "TEST",
            },
        )
        self.assertEqual(response.status_code, 200)

        other_user = get_user_model().objects.create_user(
            username="other1", password=uuid.uuid4().hex, email="other1@researchhub.com"
        )

        # Act
        self.client.force_authenticate(other_user)
        response = self.client.get("/api/note/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)

    def test_user_cannot_list_other_users_note_contents(self):
        # Arrange
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "title": "TEST",
            },
        )
        note = response.data
        response = self.client.post(
            "/api/note_content/",
            {
                "full_src": "private note body",
                "note": note["id"],
                "plain_text": "private note body",
            },
        )
        self.assertEqual(response.status_code, 200)

        other_user = get_user_model().objects.create_user(
            username="other2", password=uuid.uuid4().hex, email="other2@researchhub.com"
        )

        # Act
        self.client.force_authenticate(other_user)
        response = self.client.get("/api/note_content/")

        # Assert
        self.assertEqual(response.status_code, 405)
        self.assertNotIn("private note body", str(response.data))

    def test_org_member_can_list_org_notes(self):
        # Arrange
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        self.assertEqual(response.status_code, 200)

        member_user = get_user_model().objects.create_user(
            username="member1",
            password=uuid.uuid4().hex,
            email="email1@researchhub.com",
        )

        Permission.objects.create(
            access_type="MEMBER",
            content_type=self.organization_ct,
            object_id=self.org["id"],
            user=member_user,
        )

        # Act
        self.client.force_authenticate(member_user)
        response = self.client.get("/api/note/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_viewer_can_list_notes(self):
        # Arrange
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        self.assertEqual(response.status_code, 200)
        note = response.data

        viewer_user = get_user_model().objects.create_user(
            username="viewer1",
            password=uuid.uuid4().hex,
            email="viewer1@researchhub.com",
        )

        Permission.objects.create(
            access_type="VIEWER",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=viewer_user,
        )

        # Act
        self.client.force_authenticate(viewer_user)
        response = self.client.get("/api/note/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_create_workspace_note(self):
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        created_note = response.data
        self.assertEqual(created_note["access"], "WORKSPACE")

    def test_create_private_note(self):
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        created_note = response.data
        self.assertEqual(created_note["access"], "PRIVATE")

    def test_delete_private_note(self):
        created_response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": self.org["slug"],
                "title": "TO BE DELETED",
            },
        )
        created_note = created_response.data
        response = self.client.post(f"/api/note/{created_note['id']}/delete/")
        self.assertEqual(response.status_code, 200)

    def test_cannot_create_shared_note_manually(self):
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "SHARED",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        created_note = response.data

        # NOTE: Should only be able to created SHARED note by inviting useres
        self.assertNotEqual(created_note["access"], "SHARED")

    def test_note_editor_can_invite_others(self):
        """
        Note editors should be able to invite others to the note
        because the `IsOrganizationUser` permission class allows for this.
        """
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Create another user
        editor_user = get_user_model().objects.create_user(
            username="editor@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="editor@researchhub_test.com",
        )

        # Add permission to user
        Permission.objects.create(
            access_type="EDITOR",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=editor_user,
        )

        # Authenticate user and invite
        self.client.force_authenticate(editor_user)
        response = self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                "access_type": "ADMIN",
                "email": "invited@researchhub_test.com",
                "expire": 10080,
            },
        )

        # Get new permissions
        self.assertEqual(response.status_code, 200)

    def test_note_editor_can_update_contents(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Create another user
        editor_user = get_user_model().objects.create_user(
            username="editor@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="editor@researchhub_test.com",
        )

        # Add permission to user
        Permission.objects.create(
            access_type="EDITOR",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=editor_user,
        )

        # Update title
        response = self.client.patch(
            f"/api/note/{note['id']}/", {"title": "some title"}
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note["title"], "some title")

        # Update body
        response = self.client.post(
            "/api/note_content/",
            {
                "full_src": "updated body",
                "note": note["id"],
                "plain_text": "updated body",
            },
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note["latest_version"]["plain_text"], "updated body")

    def test_note_viewer_cannot_update_contents(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "original title",
            },
        )
        note = response.data

        # Create another user
        viewer_user = get_user_model().objects.create_user(
            username="editor@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="editor@researchhub_test.com",
        )

        # Add permission to user
        Permission.objects.create(
            access_type="VIEWER",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=viewer_user,
        )

        # Authenticate as viewer
        self.client.force_authenticate(viewer_user)

        # Update title
        response = self.client.patch(
            f"/api/note/{note['id']}/", {"title": "updated title"}
        )
        self.assertEqual(response.status_code, 403)

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note["title"], "original title")

        # Update body
        response = self.client.post(
            "/api/note_content/",
            {"full_src": "updated body", "note": note["id"], "plain_text": ""},
        )
        self.assertEqual(response.status_code, 403)

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note["latest_version"], None)

    def test_note_viewer_can_invite_others(self):
        """
        Note viewers should be able to invite others to the note
        because the `IsOrganizationUser` permission class allows for this.
        """
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Create another user
        invited_viewer = get_user_model().objects.create_user(
            username="editor@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="editor@researchhub_test.com",
        )

        # Add permission to user
        Permission.objects.create(
            access_type="VIEWER",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=invited_viewer,
        )

        # Authenticate user and invite
        self.client.force_authenticate(invited_viewer)
        response = self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                "access_type": "ADMIN",
                "email": "invited@researchhub_test.com",
                "expire": 10080,
            },
        )

        # Get new permissions
        self.assertEqual(response.status_code, 200)

    def test_note_admin_can_invite_others(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Create another user
        invited_note_admin = get_user_model().objects.create_user(
            username="admin@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="admin@researchhub_test.com",
        )

        # Add permission to user
        Permission.objects.create(
            access_type="ADMIN",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=invited_note_admin,
        )

        # Authenticate user and invite
        self.client.force_authenticate(invited_note_admin)
        response = self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                "access_type": "ADMIN",
                "email": "invited@researchhub_test.com",
                "expire": 10080,
            },
        )

        # Get new permissions
        self.assertEqual(response.status_code, 200)
        note = Note.objects.get(id=note["id"])
        p = note.permissions.get(user=invited_note_admin.id)
        self.assertTrue(p)

    def test_invited_user_cannot_create_org_notes(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Create another user
        invited_note_admin = get_user_model().objects.create_user(
            username="admin@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="admin@researchhub_test.com",
        )

        # Add permission to user
        Permission.objects.create(
            access_type="ADMIN",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=invited_note_admin,
        )

        # Authenticate user and create org note
        self.client.force_authenticate(invited_note_admin)
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_removing_note_org_access_makes_note_private(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Remove org permission
        self.client.delete(
            f"/api/note/{note['id']}/remove_permission/",
            {"organization": self.org["id"]},
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data

        self.assertEqual(note["access"], "PRIVATE")

    def test_sharing_private_note_move_to_shared_context(self):
        # create private note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Invite another user
        self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                "access_type": "ADMIN",
                "email": "invited@researchhub_test.com",
                "expire": 10080,
            },
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data

        self.assertEqual(note["access"], "SHARED")

    def test_removing_invited_user_from_shared_note_moves_note_to_private_context(self):
        # create private note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Invite another user
        self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                "access_type": "ADMIN",
                "email": "invited@researchhub_test.com",
                "expire": 10080,
            },
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note["access"], "SHARED")

        # Remove user access
        self.client.patch(
            f"/api/note/{note['id']}/remove_invited_user/",
            {"email": "invited@researchhub_test.com"},
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note["access"], "PRIVATE")

    def test_user_with_both_viewer_and_org_permission_able_to_edit_note(self):
        # create note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Create viewer user
        viewer_user = get_user_model().objects.create_user(
            username="user_b@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="user_b@researchhub_test.com",
        )

        # Add permission to user
        Permission.objects.create(
            access_type="VIEWER",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=viewer_user,
        )

        # Upgrade user to org member
        Permission.objects.create(
            access_type="MEMBER",
            content_type=self.organization_ct,
            object_id=self.org["id"],
            user=viewer_user,
        )

        # authenticate and update note
        self.client.force_authenticate(viewer_user)
        response = self.client.patch(
            f"/api/note/{note['id']}/", {"title": "some title"}
        )

        # refetch note
        response = self.client.patch(f"/api/note/{note['id']}/")
        self.assertEqual(response.data["title"], "some title")

    def test_note_admin_can_make_private(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "original title",
            },
        )
        note = response.data

        # Create another user
        admin_user = get_user_model().objects.create_user(
            username="admin@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="admin@researchhub_test.com",
        )

        # Add permission to user
        Permission.objects.create(
            access_type="ADMIN",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=admin_user,
        )

        # Authenticate as viewer
        self.client.force_authenticate(admin_user)

        # Make Private
        response = self.client.post(f"/api/note/{note['id']}/make_private/")
        self.assertEqual(response.data["access"], "PRIVATE")

    def test_note_editor_can_make_private(self):
        """
        Editors should be able to make notes private, because the
        `HasOrgEditingPermission` permission class allows for this.
        """
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "original title",
            },
        )
        self.assertTrue(response.status_code, 201)
        note = response.data

        # Create another user
        editor_user = get_user_model().objects.create_user(
            username="editor@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="editor@researchhub_test.com",
        )

        # Add permission to user
        Permission.objects.create(
            access_type="EDITOR",
            content_type=self.unified_doc_ct,
            object_id=note["unified_document"]["id"],
            user=editor_user,
        )

        # Authenticate as viewer
        self.client.force_authenticate(editor_user)

        # Make Private
        response = self.client.post(f"/api/note/{note['id']}/make_private/")
        self.assertEqual(response.status_code, 200)

    def test_org_member_can_make_private(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "original title",
            },
        )
        note = response.data

        # Create another user
        member_user = get_user_model().objects.create_user(
            username="member@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="member@researchhub_test.com",
        )

        # Add second user
        Permission.objects.create(
            access_type="MEMBER",
            content_type=self.organization_ct,
            object_id=self.org["id"],
            user=member_user,
        )

        # Authenticate as viewer
        self.client.force_authenticate(member_user)

        # Make Private
        response = self.client.post(f"/api/note/{note['id']}/make_private/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["access"], "PRIVATE")

    def test_org_member_can_remove_workspace_note(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "some note to be deleted",
            },
        )
        note = response.data

        # Create another user
        member_user = get_user_model().objects.create_user(
            username="member@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="member@researchhub_test.com",
        )

        # Add user
        Permission.objects.create(
            access_type="MEMBER",
            content_type=self.organization_ct,
            object_id=self.org["id"],
            user=member_user,
        )

        # Authenticate as viewer
        self.client.force_authenticate(member_user)

        # Delete
        response = self.client.delete(f"/api/note/{note['id']}/delete/")
        self.assertEqual(response.status_code, 200)

        # Make sure note is removed
        response = self.client.get(
            f"/api/organization/{self.org['slug']}/get_organization_notes/"
        )
        self.assertEqual(response.data["count"], 0)

    def test_org_member_making_private_note(self):
        """
        Tests creating a private note, moving it to the workspace,
        and having another user set the note back to private
        """
        # Create a user
        alice = get_user_model().objects.create_user(
            username="alice@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="alice@researchhub_test.com",
        )
        alice_org = alice.organization

        self.client.force_authenticate(alice)

        bob = get_user_model().objects.create_user(
            username="bob@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="bob@researchhub_test.com",
        )
        # Add Bob as Admin to Alice Org
        content_type = ContentType.objects.get_for_model(Organization)
        Permission.objects.create(
            access_type="ADMIN",
            content_type=content_type,
            object_id=alice_org.id,
            user=bob,
        )

        response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": alice_org.slug,
                "title": "private to workspace to private",
            },
        )
        note = response.data

        # Change note to workspace
        self.client.patch(
            f"/api/note/{note['id']}/update_permissions/",
            {
                "access_type": "ADMIN",
                "organization": alice_org.id,
            },
        )
        updated_note = self.client.get(f"/api/note/{note['id']}/")
        self.assertEqual(updated_note.data["access"], "WORKSPACE")

        # Switch to Bob
        self.client.force_authenticate(bob)

        # Make the note private
        response = self.client.post(f"/api/note/{note['id']}/make_private/")
        self.assertEqual(response.data["access"], "PRIVATE")

        bobs_notes_from_alice_org = self.client.get(
            f"/api/organization/{alice_org.slug}/get_organization_notes/"
        )
        self.assertEqual(
            bobs_notes_from_alice_org.data["results"][0]["access"], "PRIVATE"
        )

        # Switch to Alice
        self.client.force_authenticate(alice)

        alice_notes_from_alice_org = self.client.get(
            f"/api/organization/{alice_org.slug}/get_organization_notes/"
        )

        self.assertEqual(alice_notes_from_alice_org.data["count"], 0)

        response = self.client.get(f"/api/note/{note['id']}/")
        self.assertEqual(response.status_code, 403)

    def test_user_can_delete_own_org_templates(self):
        # Create template
        response = self.client.post(
            "/api/note_template/",
            {
                "full_src": "test",
                "is_default": False,
                "organization": self.org["id"],
                "name": "NON-DEFAULT TEMPLATE",
            },
        )
        template = response.data

        # Delete template
        delete_response = self.client.post(
            f"/api/note_template/{template['id']}/delete/"
        )

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.data["is_removed"], True)

    def test_user_cannot_delete_default_template(self):
        # Create template
        response = self.client.post(
            "/api/note_template/",
            {
                "full_src": "test",
                "is_default": True,
                "organization": self.org["id"],
                "name": "DEFAULT TEMPLATE",
            },
        )
        template = response.data

        # Delete template
        delete_response = self.client.post(
            f"/api/note_template/{template['id']}/delete/"
        )

        self.assertEqual(delete_response.status_code, 403)
        self.assertEqual(delete_response.data["is_removed"], False)

    def test_user_cannot_list_other_orgs_note_templates(self):
        # Arrange
        response = self.client.post(
            "/api/note_template/",
            {
                "full_src": "org template body",
                "is_default": False,
                "organization": self.org["id"],
                "name": "ORG TEMPLATE",
            },
        )
        self.assertEqual(response.status_code, 200)
        template = response.data

        other_user = get_user_model().objects.create_user(
            username="other3", password=uuid.uuid4().hex, email="other3@researchhub.com"
        )

        # Act
        self.client.force_authenticate(other_user)
        list_response = self.client.get("/api/note_template/")
        retrieve_response = self.client.get(f"/api/note_template/{template['id']}/")

        # Assert
        self.assertEqual(list_response.status_code, 200)
        self.assertNotIn("ORG TEMPLATE", str(list_response.data))
        self.assertEqual(retrieve_response.status_code, 404)

    def test_user_cannot_delete_other_orgs_note_template(self):
        # Arrange
        response = self.client.post(
            "/api/note_template/",
            {
                "full_src": "org template body",
                "is_default": False,
                "organization": self.org["id"],
                "name": "ORG TEMPLATE",
            },
        )
        self.assertEqual(response.status_code, 200)
        template = response.data

        other_user = get_user_model().objects.create_user(
            username="other4", password=uuid.uuid4().hex, email="other4@researchhub.com"
        )

        # Act
        self.client.force_authenticate(other_user)
        response = self.client.post(f"/api/note_template/{template['id']}/delete/")

        # Assert
        self.assertEqual(response.status_code, 404)
        self.assertFalse(NoteTemplate.objects.get(id=template["id"]).is_removed)

    def test_any_user_can_list_default_note_templates(self):
        # Arrange
        response = self.client.post(
            "/api/note_template/",
            {
                "full_src": "default template body",
                "is_default": True,
                "name": "DEFAULT TEMPLATE",
            },
        )
        self.assertEqual(response.status_code, 200)

        other_user = get_user_model().objects.create_user(
            username="other5", password=uuid.uuid4().hex, email="other5@researchhub.com"
        )

        # Act
        self.client.force_authenticate(other_user)
        response = self.client.get("/api/note_template/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("DEFAULT TEMPLATE", str(response.data))

    def test_org_member_can_delete_org_note_template(self):
        # Arrange
        response = self.client.post(
            "/api/note_template/",
            {
                "full_src": "org template body",
                "is_default": False,
                "organization": self.org["id"],
                "name": "ORG TEMPLATE",
            },
        )
        self.assertEqual(response.status_code, 200)
        template = response.data

        member_user = get_user_model().objects.create_user(
            username="member2",
            password=uuid.uuid4().hex,
            email="member2@researchhub.com",
        )
        Permission.objects.create(
            access_type="MEMBER",
            content_type=self.organization_ct,
            object_id=self.org["id"],
            user=member_user,
        )

        # Act
        self.client.force_authenticate(member_user)
        response = self.client.post(f"/api/note_template/{template['id']}/delete/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertTrue(NoteTemplate.objects.get(id=template["id"]).is_removed)

    def test_note_content_json_functionality(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        # Test creating content with full_json
        test_json = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Test JSON Content"}],
                }
            ],
        }

        response = self.client.post(
            "/api/note_content/",
            {
                "full_json": test_json,
                "note": note["id"],
                "plain_text": "Test JSON Content",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["json"], test_json)
        self.assertIsNone(response.data["src"])

        # Re-fetch note to verify json is saved
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note["latest_version"]["json"], test_json)
        self.assertIsNone(note["latest_version"]["src"])

    def test_note_content_json_priority_over_src(self):
        # Create workspace note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        note = response.data

        test_json = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Test JSON Content"}],
                }
            ],
        }

        # Update content with both full_json and full_src
        response = self.client.post(
            "/api/note_content/",
            {
                "full_json": test_json,
                "full_src": "This src content should be ignored",
                "note": note["id"],
                "plain_text": "Test JSON Content",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["json"], test_json)
        self.assertIsNone(response.data["src"])  # src should be None when json exists

        # Re-fetch note to verify only json was saved
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note["latest_version"]["json"], test_json)
        self.assertIsNone(note["latest_version"]["src"])

    def test_note_without_post(self):
        # Create a note without an associated post
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Note without post",
            },
        )
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Verify that post is None
        self.assertIsNone(note["post"])

    def test_note_with_post(self):
        # Create a note first
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Note with post",
            },
        )
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Create a post associated with the note
        post_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": self.user.id,
                "full_src": "Test post content",
                "is_public": True,
                "note_id": note["id"],
                "renderable_text": (
                    "Test post content that is sufficiently long for validation"
                ),
                "title": "Test post title that is sufficiently long",
                "hubs": [],
            },
        )
        self.assertEqual(post_response.status_code, 200)

        # Re-fetch the note to verify post data
        response = self.client.get(f"/api/note/{note['id']}/")
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Verify post data is present and correctly structured
        self.assertIsNotNone(note["post"])
        self.assertIn("authors", note["post"])
        self.assertIn("hubs", note["post"])
        self.assertIn("unified_document", note["post"])

    def test_note_with_preregistration_post_fundraise(self):
        # Create a note first
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Note with preregistration post",
            },
        )
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Create a preregistration post with fundraise
        post_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "PREREGISTRATION",
                "created_by": self.user.id,
                "full_src": "Test post content",
                "is_public": True,
                "note_id": note["id"],
                "renderable_text": (
                    "Test post content that is sufficiently long for validation"
                ),
                "title": "Test post title that is sufficiently long",
                "hubs": [],
                "fundraise_goal_amount": 1000,
            },
        )
        self.assertEqual(post_response.status_code, 200)

        # Re-fetch the note to verify post data
        response = self.client.get(f"/api/note/{note['id']}/")
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Verify fundraise data is present
        self.assertIsNotNone(note["post"]["unified_document"]["fundraise"])
        self.assertEqual(
            note["post"]["unified_document"]["fundraise"]["goal_amount"]["usd"], 1000.0
        )

    def test_note_with_grant_post(self):
        # Create a note first
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Note with grant post",
            },
        )
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Create a grant post
        post_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": self.user.id,
                "full_src": "Test grant post content",
                "is_public": True,
                "note_id": note["id"],
                "renderable_text": (
                    "Test grant post content that is sufficiently long for validation"
                ),
                "title": "Test grant post title that is sufficiently long",
                "hubs": [],
                "grant_amount": 50000,
                "grant_currency": "USD",
                "grant_organization": "National Science Foundation",
                "grant_description": "Research grant for AI applications",
            },
        )
        self.assertEqual(post_response.status_code, 200)

        # Re-fetch the note to verify post data
        response = self.client.get(f"/api/note/{note['id']}/")
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Verify grant data is present in the unified document
        self.assertIsNotNone(note["post"]["unified_document"]["grant"])

        grant_data = note["post"]["unified_document"]["grant"]
        self.assertEqual(grant_data["amount"]["usd"], 50000.0)
        self.assertEqual(grant_data["organization"], "National Science Foundation")
        self.assertEqual(
            grant_data["description"], "Research grant for AI applications"
        )
        self.assertEqual(grant_data["status"], "PENDING")
        self.assertIn("created_by", grant_data)

    def test_note_with_grant_post_includes_contacts_and_applications(self):
        # Create users to be contacts
        contact1 = get_user_model().objects.create_user(
            username="contact1",
            password=uuid.uuid4().hex,
            email="contact1@researchhub.com",
        )
        contact2 = get_user_model().objects.create_user(
            username="contact2",
            password=uuid.uuid4().hex,
            email="contact2@researchhub.com",
        )

        # Create a note first
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Note with grant post including contacts",
            },
        )
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Create a grant post with contacts
        post_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": self.user.id,
                "full_src": "Test grant post content with contacts",
                "is_public": True,
                "note_id": note["id"],
                "renderable_text": (
                    "Test grant post content with contacts that is "
                    "sufficiently long for validation"
                ),
                "title": (
                    "Test grant post with contacts title that is sufficiently long"
                ),
                "hubs": [],
                "grant_amount": 75000,
                "grant_currency": "USD",
                "grant_organization": "National Science Foundation with Contacts",
                "grant_description": "Research grant for AI applications with contacts",
                "grant_contacts": [contact1.id, contact2.id],
            },
        )
        self.assertEqual(post_response.status_code, 200)

        # Re-fetch the note to verify grant data includes contacts and applications
        response = self.client.get(f"/api/note/{note['id']}/")
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Verify grant data is present
        self.assertIsNotNone(note["post"]["unified_document"]["grant"])
        grant_data = note["post"]["unified_document"]["grant"]

        # Verify basic grant fields
        self.assertEqual(grant_data["amount"]["usd"], 75000.0)
        self.assertEqual(
            grant_data["organization"], "National Science Foundation with Contacts"
        )
        self.assertEqual(
            grant_data["description"],
            "Research grant for AI applications with contacts",
        )

        # Verify contacts field is present and contains the expected contacts
        self.assertIn("contacts", grant_data)
        self.assertEqual(len(grant_data["contacts"]), 2)
        contact_ids = [contact["id"] for contact in grant_data["contacts"]]
        self.assertIn(contact1.id, contact_ids)
        self.assertIn(contact2.id, contact_ids)

        # Verify each contact has expected fields
        for contact in grant_data["contacts"]:
            self.assertIn("id", contact)
            self.assertIn("first_name", contact)
            self.assertIn("last_name", contact)
            self.assertIn("author_profile", contact)

        # Verify applications field is present (should be empty initially)
        self.assertIn("applications", grant_data)
        self.assertEqual(grant_data["applications"], [])

    def test_get_organization_notes_status_draft(self):
        # Create two notes: one draft (no post) and one published (with post)
        draft_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Draft note",
            },
        )
        self.assertEqual(draft_response.status_code, 200)

        published_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Published note",
            },
        )
        self.assertEqual(published_response.status_code, 200)
        published_note = published_response.data

        # Publish the second note by creating an associated post
        post_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": self.user.id,
                "full_src": "Test post content",
                "is_public": True,
                "note_id": published_note["id"],
                "renderable_text": (
                    "Test post content that is sufficiently long for validation"
                ),
                "title": "Test post title that is sufficiently long",
                "hubs": [],
            },
        )
        self.assertEqual(post_response.status_code, 200)

        # Fetch only draft notes
        response = self.client.get(
            f"/api/organization/{self.org['slug']}/get_organization_notes/?status=DRAFT"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Draft note")

    def test_get_organization_notes_status_published(self):
        # Create two notes: one draft (no post) and one published (with post)
        self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Draft note",
            },
        )

        published_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Published note",
            },
        )
        self.assertEqual(published_response.status_code, 200)
        published_note = published_response.data

        # Publish the second note by creating an associated post
        post_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": self.user.id,
                "full_src": "Test post content",
                "is_public": True,
                "note_id": published_note["id"],
                "renderable_text": (
                    "Test post content that is sufficiently long for validation"
                ),
                "title": "Test post title that is sufficiently long",
                "hubs": [],
            },
        )
        self.assertEqual(post_response.status_code, 200)

        # Fetch only published notes
        response = self.client.get(
            f"/api/organization/{self.org['slug']}/get_organization_notes/?status=PUBLISHED"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Published note")

    def test_create_note_with_document_type_sets_field(self):
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Grant draft",
                "document_type": "GRANT",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["document_type"], "GRANT")

        note = Note.objects.get(id=response.data["id"])
        self.assertEqual(note.document_type, "GRANT")

    def test_create_note_without_document_type_leaves_field_null(self):
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Plain note",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["document_type"])

        note = Note.objects.get(id=response.data["id"])
        self.assertIsNone(note.document_type)

    def test_get_organization_notes_filter_by_type(self):
        # Create notes with different document types
        self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Grant note",
                "document_type": "GRANT",
            },
        )
        self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Preregistration note",
                "document_type": "PREREGISTRATION",
            },
        )
        self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Untyped note",
            },
        )

        # Filter by GRANT
        response = self.client.get(
            f"/api/organization/{self.org['slug']}/get_organization_notes/?type=GRANT"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Grant note")
        self.assertEqual(response.data["results"][0]["document_type"], "GRANT")

        # Filter by PREREGISTRATION
        response = self.client.get(
            f"/api/organization/{self.org['slug']}/get_organization_notes/?type=PREREGISTRATION"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Preregistration note")

    def test_get_organization_notes_filter_by_type_and_status(self):
        # Create a draft GRANT note and a published GRANT note
        self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Draft grant",
                "document_type": "GRANT",
            },
        )

        published_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Published grant",
                "document_type": "GRANT",
            },
        )
        published_note = published_response.data

        self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": self.user.id,
                "full_src": "Grant post content",
                "is_public": True,
                "note_id": published_note["id"],
                "renderable_text": (
                    "Grant post content that is sufficiently long for validation"
                ),
                "title": "Grant post title that is sufficiently long",
                "hubs": [],
                "grant_amount": 50000,
                "grant_currency": "USD",
                "grant_organization": "Test Foundation",
                "grant_description": "Test grant description",
            },
        )

        # Filter for draft GRANTs only
        response = self.client.get(
            f"/api/organization/{self.org['slug']}/get_organization_notes/"
            f"?status=DRAFT&type=GRANT"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Draft grant")

    def test_note_with_grant_applications_serialization(self):
        # Create applicant user (must be verified to create preregistration post)
        applicant = get_user_model().objects.create_user(
            username="applicant",
            password=uuid.uuid4().hex,
            email="applicant@researchhub.com",
        )
        make_user_verified(applicant)

        # Create a note first
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Note with grant applications",
            },
        )
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Create a grant post
        post_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": self.user.id,
                "full_src": "Test grant post for applications",
                "is_public": True,
                "note_id": note["id"],
                "renderable_text": (
                    "Test grant post for applications that is "
                    "sufficiently long for validation"
                ),
                "title": "Test grant with applications title that is sufficiently long",
                "hubs": [],
                "grant_amount": 60000,
                "grant_currency": "USD",
                "grant_organization": "Application Test Foundation",
                "grant_description": "Research grant for testing applications",
            },
        )
        self.assertEqual(post_response.status_code, 200)

        # Create a preregistration post for the applicant to apply with
        self.client.force_authenticate(applicant)
        preregistration_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "PREREGISTRATION",
                "created_by": applicant.id,
                "full_src": "Preregistration content for application",
                "is_public": True,
                "renderable_text": (
                    "Preregistration content for application that is "
                    "sufficiently long for validation"
                ),
                "title": (
                    "Preregistration for grant application that is sufficiently long"
                ),
                "hubs": [],
            },
        )
        self.assertEqual(preregistration_response.status_code, 200)
        ResearchhubUnifiedDocument.objects.filter(
            id=preregistration_response.data["unified_document"]["id"]
        ).update(status=ResearchhubUnifiedDocument.APPROVED)

        # Apply to the grant
        from purchase.models import Grant, GrantApplication

        grant = Grant.objects.get(
            unified_document=post_response.data["unified_document"]["id"]
        )
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post_id=preregistration_response.data["id"],
            applicant=applicant,
        )

        # Switch back to original user to fetch the note
        self.client.force_authenticate(self.user)

        # Re-fetch the note to verify applications are included
        response = self.client.get(f"/api/note/{note['id']}/")
        self.assertEqual(response.status_code, 200)
        note = response.data

        # Verify grant data is present
        self.assertIsNotNone(note["post"]["unified_document"]["grant"])
        grant_data = note["post"]["unified_document"]["grant"]

        # Verify applications field is present and contains the application
        self.assertIn("applications", grant_data)
        self.assertEqual(len(grant_data["applications"]), 1)

        application = grant_data["applications"][0]
        self.assertIn("id", application)
        self.assertIn("created_date", application)
        self.assertIn("applicant", application)
        self.assertIn("preregistration_post_id", application)
        self.assertEqual(application["applicant"]["id"], applicant.author_profile.id)
        self.assertEqual(
            application["preregistration_post_id"], preregistration_response.data["id"]
        )

    def test_adds_replaces_and_removes_selected_grant(self) -> None:
        """A draft can manage its grant without violating its document type."""
        # Arrange
        first_grant = self._create_grant()
        second_grant = self._create_grant()

        # Act
        create_response = self.client.post("/api/note/")
        note_id = create_response.data["id"]
        add_response = self.client.patch(
            f"/api/note/{note_id}/",
            {
                "document_type": PREREGISTRATION,
                "selected_grant": first_grant.id,
            },
        )
        replace_response = self.client.patch(
            f"/api/note/{note_id}/",
            {"selected_grant": second_grant.id},
        )
        retain_response = self.client.patch(
            f"/api/note/{note_id}/",
            {"document_type": DISCUSSION},
        )
        remove_response = self.client.patch(
            f"/api/note/{note_id}/",
            {"document_type": DISCUSSION, "selected_grant": None},
        )

        # Assert
        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(add_response.status_code, 200)
        self.assertEqual(add_response.data["document_type"], PREREGISTRATION)
        self.assertEqual(add_response.data["selected_grant"], first_grant.id)
        self.assertEqual(
            add_response.data["selected_grant_details"]["short_title"], "Kindness RFP"
        )
        self.assertEqual(replace_response.status_code, 200)
        self.assertEqual(replace_response.data["selected_grant"], second_grant.id)
        self.assertEqual(retain_response.status_code, 400)
        self.assertEqual(remove_response.status_code, 200)
        self.assertEqual(remove_response.data["document_type"], DISCUSSION)
        self.assertIsNone(remove_response.data["selected_grant"])

    def test_rejects_invalid_selected_grant_changes(self) -> None:
        """Selections reject invalid note, grant, and publication states."""
        # Arrange
        active_grant = self._create_grant()
        inactive_grant = self._create_grant(status=Grant.CLOSED)
        removed_grant = self._create_grant()
        removed_grant.unified_document.is_removed = True
        removed_grant.unified_document.save(update_fields=["is_removed"])
        note_response = self.client.post(
            "/api/note/",
            {
                "document_type": PREREGISTRATION,
                "selected_grant": active_grant.id,
            },
        )
        note = Note.objects.get(id=note_response.data["id"])
        post = create_post(created_by=self.user, document_type=PREREGISTRATION)
        post.note = note
        post.save(update_fields=["note"])

        # Act
        wrong_type_response = self.client.post(
            "/api/note/",
            {"document_type": DISCUSSION, "selected_grant": active_grant.id},
        )
        removed_response = self.client.post(
            "/api/note/",
            {
                "document_type": PREREGISTRATION,
                "selected_grant": removed_grant.id,
            },
        )
        inactive_response = self.client.post(
            "/api/note/",
            {
                "document_type": PREREGISTRATION,
                "selected_grant": inactive_grant.id,
            },
        )
        published_response = self.client.patch(
            f"/api/note/{note.id}/",
            {"selected_grant": None},
        )
        published_draft_response = self.client.patch(
            f"/api/note/{note.id}/",
            {"preregistration_settings": {"is_public": True}},
        )

        # Assert
        self.assertEqual(wrong_type_response.status_code, 400)
        self.assertEqual(removed_response.status_code, 400)
        self.assertEqual(inactive_response.status_code, 400)
        self.assertEqual(published_response.status_code, 409)
        self.assertEqual(published_draft_response.status_code, 409)

    def test_creates_note_with_draft_details(self) -> None:
        """A create request stores the cover, byline, and hubs."""
        # Arrange
        first_author = Author.objects.create(first_name="Ada", last_name="Lovelace")
        second_author = Author.objects.create(first_name="Grace", last_name="Hopper")
        hub = create_hub(name="Molecular Biology")

        # Act
        response = self.client.post(
            "/api/note/",
            {
                "author_ids": [second_author.id, first_author.id],
                "hub_ids": [hub.id],
                "image": "notes/cover.png",
                "preview_img": "https://www.researchhub.com/cover.png",
                "title": "Draft with details",
            },
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["image"], "notes/cover.png")
        self.assertEqual(
            response.data["preview_img"], "https://www.researchhub.com/cover.png"
        )
        self.assertEqual(
            [author["id"] for author in response.data["authors"]],
            [second_author.id, first_author.id],
        )
        self.assertEqual(
            [hub_data["id"] for hub_data in response.data["hubs"]], [hub.id]
        )

    def test_creates_note_with_legacy_hub_input(self) -> None:
        """A create request may still send its topics as the legacy hubs list."""
        # Arrange
        hub = create_hub(name="Neuroscience")

        # Act
        response = self.client.post(
            "/api/note/", {"hubs": [hub.id], "title": "Legacy"}
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [hub_data["id"] for hub_data in response.data["hubs"]], [hub.id]
        )

    def test_patches_draft_details_partially(self) -> None:
        """A patch changes only what it sends and never touches real topics."""
        # Arrange
        author = Author.objects.create(first_name="Ada", last_name="Lovelace")
        replacement_author = Author.objects.create(
            first_name="Alan", last_name="Turing"
        )
        first_hub = create_hub(name="Genetics")
        second_hub = create_hub(name="Immunology")
        note_id = self.client.post(
            "/api/note/",
            {
                "author_ids": [author.id],
                "hub_ids": [first_hub.id],
                "image": "notes/cover.png",
            },
        ).data["id"]
        topic = Topic.objects.create(openalex_id="T1", display_name="Genomics")
        UnifiedDocumentTopics.objects.create(
            unified_document=Note.objects.get(id=note_id).unified_document, topic=topic
        )

        # Act
        replace_response = self.client.patch(
            f"/api/note/{note_id}/",
            {
                "author_ids": [replacement_author.id],
                "hub_ids": [second_hub.id],
                "title": "Renamed",
            },
        )
        clear_response = self.client.patch(
            f"/api/note/{note_id}/",
            {"author_ids": [], "image": ""},
        )

        # Assert
        self.assertEqual(replace_response.status_code, 200)
        self.assertEqual(
            [author_data["id"] for author_data in replace_response.data["authors"]],
            [replacement_author.id],
        )
        self.assertEqual(
            [hub_data["id"] for hub_data in replace_response.data["hubs"]],
            [second_hub.id],
        )
        self.assertEqual(replace_response.data["image"], "notes/cover.png")
        self.assertEqual(clear_response.status_code, 200)
        self.assertEqual(clear_response.data["authors"], [])
        self.assertEqual(clear_response.data["image"], "")
        self.assertEqual(clear_response.data["title"], "Renamed")
        self.assertEqual(
            list(Note.objects.get(id=note_id).unified_document.topics.all()), [topic]
        )

    def test_saves_grant_settings_on_grant_note(self) -> None:
        """Grant form values round-trip without creating a live grant."""
        # Arrange
        contact = get_user_model().objects.create_user(
            username="contact@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="contact@researchhub_test.com",
            first_name="Ada",
            last_name="Lovelace",
        )
        note_id = self.client.post(
            "/api/note/", {"document_type": GRANT, "title": "RFP draft"}
        ).data["id"]

        # Act
        save_response = self.client.patch(
            f"/api/note/{note_id}/",
            {
                "grant_settings": {
                    "amount": "50000.00",
                    "application_visibility": Grant.APPLICATION_VISIBILITY_PRIVATE,
                    "contact_ids": [contact.id],
                    "currency": "USD",
                    "organization": "Kind Foundation",
                }
            },
        )
        clear_response = self.client.patch(
            f"/api/note/{note_id}/",
            {"grant_settings": {"contact_ids": [], "organization": ""}},
        )

        # Assert
        self.assertEqual(save_response.status_code, 200)
        saved_settings = save_response.data["grant_settings"]
        self.assertEqual(saved_settings["amount"], "50000.00")
        self.assertEqual(saved_settings["contact_ids"], [contact.id])
        self.assertEqual(
            saved_settings["contacts"],
            [{"id": contact.id, "first_name": "Ada", "last_name": "Lovelace"}],
        )
        self.assertEqual(
            saved_settings["application_visibility"],
            Grant.APPLICATION_VISIBILITY_PRIVATE,
        )
        self.assertEqual(clear_response.status_code, 200)
        cleared_settings = clear_response.data["grant_settings"]
        self.assertEqual(cleared_settings["contact_ids"], [])
        self.assertEqual(cleared_settings["organization"], "")
        self.assertEqual(cleared_settings["currency"], "USD")
        self.assertFalse(Grant.objects.filter(created_by=self.user).exists())

    def test_saves_preregistration_settings_on_preregistration_note(self) -> None:
        """Fundraise and visibility values round-trip without a live fundraise."""
        # Arrange
        grant = self._create_grant()
        nonprofit = NonprofitOrg.objects.create(
            name="Hope Charity", endaoment_org_id="endaoment-1"
        )
        note_id = self.client.post(
            "/api/note/",
            {"document_type": PREREGISTRATION, "selected_grant": grant.id},
        ).data["id"]

        # Act
        response = self.client.patch(
            f"/api/note/{note_id}/",
            {
                "preregistration_settings": {
                    "duration_days": 30,
                    "goal_amount": "2500.00",
                    "goal_currency": "USD",
                    "is_public": False,
                    "nonprofit_id": nonprofit.id,
                }
            },
        )
        funding_only_response = self.client.patch(
            f"/api/note/{note_id}/",
            {"preregistration_settings": {"goal_amount": "3000.00"}},
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        saved_settings = response.data["preregistration_settings"]
        self.assertEqual(saved_settings["duration_days"], 30)
        self.assertEqual(saved_settings["goal_amount"], "2500.00")
        self.assertEqual(saved_settings["nonprofit_id"], nonprofit.id)
        self.assertFalse(saved_settings["is_public"])
        self.assertEqual(saved_settings["nonprofit_details"]["name"], "Hope Charity")
        self.assertEqual(response.data["selected_grant"], grant.id)
        self.assertEqual(funding_only_response.status_code, 200)
        funding_only_settings = funding_only_response.data["preregistration_settings"]
        self.assertEqual(funding_only_settings["goal_amount"], "3000.00")
        self.assertFalse(funding_only_settings["is_public"])
        self.assertFalse(Fundraise.objects.filter(created_by=self.user).exists())

    def test_rejects_funding_details_the_document_type_does_not_use(self) -> None:
        """A mismatched funding form is refused and never overwrites saved values."""
        # Arrange
        note_id = self.client.post(
            "/api/note/", {"document_type": GRANT, "title": "RFP draft"}
        ).data["id"]
        self.client.patch(
            f"/api/note/{note_id}/",
            {"grant_settings": {"organization": "Kind Foundation"}},
        )

        # Act
        rejected_response = self.client.patch(
            f"/api/note/{note_id}/",
            {"preregistration_settings": {"duration_days": 30}},
        )
        retyped_response = self.client.patch(
            f"/api/note/{note_id}/", {"document_type": DISCUSSION}
        )
        restored_response = self.client.patch(
            f"/api/note/{note_id}/", {"document_type": GRANT}
        )

        # Assert
        self.assertEqual(rejected_response.status_code, 400)
        self.assertIn("preregistration_settings", rejected_response.data)
        self.assertFalse(PreregistrationSettings.objects.exists())
        self.assertIsNone(retyped_response.data["grant_settings"])
        self.assertEqual(
            restored_response.data["grant_settings"]["organization"],
            "Kind Foundation",
        )


class AccessibleNoteTests(APITestCase):
    organization_ct = None

    def setUp(self):
        self.organization_ct = ContentType.objects.get_for_model(Organization)

        username = "test@researchhub_test.com"
        password = uuid.uuid4().hex
        self.user = get_user_model().objects.create_user(
            username=username, password=password, email=username, moderator=True
        )
        make_user_verified(self.user)
        self.client.force_authenticate(self.user)

        response = self.client.post("/api/organization/", {"name": "some org"})
        self.org = response.data

        RscExchangeRate.objects.create(rate=4.99014625)

    def test_accessible_notes_returns_all_notes_user_can_access(self):
        # Arrange
        own_response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": self.org["slug"],
                "title": "Own private note",
            },
        )
        self.assertEqual(own_response.status_code, 200)

        org_member = get_user_model().objects.create_user(
            username="org-member@researchhub.com",
            password=uuid.uuid4().hex,
            email="org-member@researchhub.com",
        )
        Permission.objects.create(
            access_type="MEMBER",
            content_type=self.organization_ct,
            object_id=self.org["id"],
            user=org_member,
        )
        self.client.force_authenticate(org_member)
        org_note_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Workspace note from member",
            },
        )
        self.assertEqual(org_note_response.status_code, 200)

        inviter = get_user_model().objects.create_user(
            username="inviter@researchhub.com",
            password=uuid.uuid4().hex,
            email="inviter@researchhub.com",
        )
        self.client.force_authenticate(inviter)
        invited_note_response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": inviter.organization.slug,
                "title": "Accepted invite note",
            },
        )
        self.assertEqual(invited_note_response.status_code, 200)
        invite = NoteInvitation.create(
            expiration_time=1440,
            recipient=None,
            recipient_email=self.user.email,
            inviter_id=inviter.id,
            note_id=invited_note_response.data["id"],
            invite_type="EDITOR",
        )

        unrelated_user = get_user_model().objects.create_user(
            username="unrelated@researchhub.com",
            password=uuid.uuid4().hex,
            email="unrelated@researchhub.com",
        )
        self.client.force_authenticate(unrelated_user)
        unrelated_response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": unrelated_user.organization.slug,
                "title": "Unrelated note",
            },
        )
        self.assertEqual(unrelated_response.status_code, 200)

        self.client.force_authenticate(self.user)
        accept_response = self.client.post(
            f"/api/invite/note/{invite.key}/accept_invite/"
        )
        self.assertEqual(accept_response.status_code, 200)
        removed_response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": self.org["slug"],
                "title": "Removed note",
            },
        )
        self.assertEqual(removed_response.status_code, 200)
        delete_response = self.client.post(
            f"/api/note/{removed_response.data['id']}/delete/"
        )
        self.assertEqual(delete_response.status_code, 200)

        # Act
        response = self.client.get("/api/note/accessible/")

        # Assert
        self.assertEqual(response.status_code, 200)
        titles = {note["title"] for note in response.data["results"]}
        self.assertEqual(
            titles,
            {
                "Accepted invite note",
                "Own private note",
                "Workspace note from member",
            },
        )
        self.assertNotIn("Unrelated note", titles)
        self.assertNotIn("Removed note", titles)
        self.assertNotIn("latest_version", response.data["results"][0])

    def test_accessible_notes_supports_status_and_type_filters(self):
        # Arrange
        draft_grant_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Draft grant",
                "document_type": "GRANT",
            },
        )
        self.assertEqual(draft_grant_response.status_code, 200)

        published_grant_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Published grant",
                "document_type": "GRANT",
            },
        )
        self.assertEqual(published_grant_response.status_code, 200)

        draft_preregistration_response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "Draft preregistration",
                "document_type": "PREREGISTRATION",
            },
        )
        self.assertEqual(draft_preregistration_response.status_code, 200)

        post_response = self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "GRANT",
                "created_by": self.user.id,
                "full_src": "Grant post content",
                "is_public": True,
                "note_id": published_grant_response.data["id"],
                "renderable_text": (
                    "Grant post content that is sufficiently long for validation"
                ),
                "title": "Grant post title that is sufficiently long",
                "hubs": [],
                "grant_amount": 50000,
                "grant_currency": "USD",
                "grant_organization": "Test Foundation",
                "grant_description": "Test grant description",
            },
        )
        self.assertEqual(post_response.status_code, 200)

        # Act
        draft_response = self.client.get(
            "/api/note/accessible/?status=DRAFT&type=GRANT"
        )
        published_response = self.client.get(
            "/api/note/accessible/?status=PUBLISHED&type=GRANT"
        )

        # Assert
        self.assertEqual(draft_response.status_code, 200)
        self.assertEqual(draft_response.data["count"], 1)
        self.assertEqual(draft_response.data["results"][0]["title"], "Draft grant")
        self.assertEqual(draft_response.data["results"][0]["document_type"], "GRANT")

        self.assertEqual(published_response.status_code, 200)
        self.assertEqual(published_response.data["count"], 1)
        self.assertEqual(
            published_response.data["results"][0]["title"], "Published grant"
        )
