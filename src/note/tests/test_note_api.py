import uuid

from allauth.utils import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from note.models import Note
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Organization

unified_doc_content_type = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
organization_content_type = ContentType.objects.get_for_model(Organization)


class NoteTests(APITestCase):
    def setUp(self):
        # Create + auth user
        username = "test@researchhub_test.com"
        password = uuid.uuid4().hex
        self.user = get_user_model().objects.create_user(
            username=username, password=password, email=username, moderator=True
        )
        self.client.force_authenticate(self.user)

        # Create org
        response = self.client.post("/api/organization/", {"name": "some org"})
        self.org = response.data

        # Create exchange rate
        RscExchangeRate.objects.create(rate=4.99014625)

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
            content_type=organization_content_type,
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
            content_type=unified_doc_content_type,
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
            content_type=unified_doc_content_type,
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
            content_type=unified_doc_content_type,
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
            content_type=unified_doc_content_type,
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
            content_type=unified_doc_content_type,
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
            content_type=unified_doc_content_type,
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
            content_type=unified_doc_content_type,
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
            content_type=unified_doc_content_type,
            object_id=note["unified_document"]["id"],
            user=viewer_user,
        )

        # Upgrade user to org member
        Permission.objects.create(
            access_type="MEMBER",
            content_type=organization_content_type,
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
            content_type=unified_doc_content_type,
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
            content_type=unified_doc_content_type,
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
            content_type=organization_content_type,
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
            content_type=organization_content_type,
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
                    "Test grant post content that is "
                    "sufficiently long for validation"
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
        self.assertEqual(grant_data["status"], "OPEN")
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

    def test_note_with_grant_applications_serialization(self):
        # Create applicant user
        applicant = get_user_model().objects.create_user(
            username="applicant",
            password=uuid.uuid4().hex,
            email="applicant@researchhub.com",
        )

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

    def test_user_can_filter_notes_by_document_type(self):
        """Test that users can filter notes by unified document's document type"""
        # Create a note with NOTE document type (default)
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "title": "Test Note",
            },
        )
        self.assertEqual(response.status_code, 200)
        note_with_note_type = response.data

        # Create another unified document with different document type
        from researchhub_document.related_models.constants.document_type import PAPER

        unified_doc_paper = ResearchhubUnifiedDocument.objects.create(
            document_type=PAPER
        )

        # Create a note manually with PAPER document type
        note_with_paper_type = Note.objects.create(
            created_by=self.user,
            organization=self.user.organization,
            unified_document=unified_doc_paper,
            title="Test Paper Note",
        )

        # Add permissions for the manually created note
        content_type = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            access_type="ADMIN",
            content_type=content_type,
            object_id=unified_doc_paper.id,
            user=self.user,
        )

        # Test filtering by NOTE document type
        response = self.client.get("/api/note/?document_type=NOTE")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], note_with_note_type["id"])

        # Test filtering by PAPER document type
        response = self.client.get("/api/note/?document_type=PAPER")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], note_with_paper_type.id)

        # Test no filter returns all notes
        response = self.client.get("/api/note/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

        # Test filtering by non-existent document type returns no results
        response = self.client.get("/api/note/?document_type=NONEXISTENT")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
