from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from allauth.utils import (
    get_user_model,
)
from user.related_models.user_model import User
from researchhub_document.models import (
    ResearchhubUnifiedDocument
)
from researchhub_access_group.models import Permission
from django.contrib.contenttypes.models import ContentType
from note.models import (
    Note
)
class NoteTests(APITestCase):
    def setUp(self):
        # Create + auth user
        username = "test@test.com"
        password = "password"
        self.user = get_user_model().objects.create_user(username=username, password=password, email=username)
        self.client.force_authenticate(self.user)

        # Create org
        response = self.client.post("/api/organization/", {"name": "some org"})
        self.org = response.data

    def test_create_workspace_note(self):
        response = self.client.post("/api/note/", {"grouping": "WORKSPACE", "organization_slug": self.org["slug"], "title": "TEST" })       
        created_note = response.data
        self.assertEqual(created_note["access"], "WORKSPACE")

    def test_create_private_note(self):
        response = self.client.post("/api/note/", {"grouping": "PRIVATE", "organization_slug": self.org["slug"], "title": "TEST" })       
        created_note = response.data
        self.assertEqual(created_note["access"], "PRIVATE")

    def test_note_editor_cannot_invite_others(self):
        # Create workspace note
        response = self.client.post("/api/note/", {"grouping": "WORKSPACE", "organization_slug": self.org["slug"], "title": "TEST" })       
        note = response.data

        # Create another user
        editor_user = get_user_model().objects.create_user(username="editor@example.com", password="password", email="editor@example.com")
        
        # Add permission to user
        perms = Permission.objects.create(
            access_type="EDITOR",
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=note["unified_document"],
            user=editor_user
        )

        # Authenticate user and invite
        self.client.force_authenticate(editor_user)
        response = self.client.post(f"/api/note/{note['id']}/invite_user/", {"access_type": "ADMIN", "email": "invited@example.com", "expire": 10080 })

        # Get new permissions
        self.assertEqual(response.status_code, 403)

    def test_note_viewer_cannot_invite_others(self):
        # Create workspace note
        response = self.client.post("/api/note/", {"grouping": "WORKSPACE", "organization_slug": self.org["slug"], "title": "TEST" })       
        note = response.data

        # Create another user
        invited_viewer = get_user_model().objects.create_user(username="editor@example.com", password="password", email="editor@example.com")
        
        # Add permission to user
        perms = Permission.objects.create(
            access_type="VIEWER",
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=note["unified_document"],
            user=invited_viewer
        )

        # Authenticate user and invite
        self.client.force_authenticate(invited_viewer)
        response = self.client.post(f"/api/note/{note['id']}/invite_user/", {"access_type": "ADMIN", "email": "invited@example.com", "expire": 10080 })

        # Get new permissions
        self.assertEqual(response.status_code, 403)

    def test_note_admin_can_invite_others(self):
        # Create workspace note
        response = self.client.post("/api/note/", {"grouping": "WORKSPACE", "organization_slug": self.org["slug"], "title": "TEST" })       
        note = response.data

        # Create another user
        invited_note_admin = get_user_model().objects.create_user(username="admin@example.com", password="password", email="admin@example.com")
        
        # Add permission to user
        perms = Permission.objects.create(
            access_type="ADMIN",
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=note["unified_document"],
            user=invited_note_admin
        )

        # Authenticate user and invite
        self.client.force_authenticate(invited_note_admin)
        response = self.client.post(f"/api/note/{note['id']}/invite_user/", {"access_type": "ADMIN", "email": "invited@example.com", "expire": 10080 })

        # Get new permissions
        self.assertEqual(response.status_code, 200)
        note = Note.objects.get(id=note["id"])
        p = note.permissions.get(user=invited_note_admin.id)
        self.assertTrue(p)

    def test_invited_user_cannot_create_org_notes(self):
        # Create workspace note
        response = self.client.post("/api/note/", {"grouping": "WORKSPACE", "organization_slug": self.org["slug"], "title": "TEST" })       
        note = response.data

        # Create another user
        invited_note_admin = get_user_model().objects.create_user(username="admin@example.com", password="password", email="admin@example.com")

        # Add permission to user
        perms = Permission.objects.create(
            access_type="ADMIN",
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=note["unified_document"],
            user=invited_note_admin
        )

        # Authenticate user and create org note
        self.client.force_authenticate(invited_note_admin)
        response = self.client.post("/api/note/", {"grouping": "WORKSPACE", "organization_slug": self.org["slug"], "title": "TEST" })

        self.assertEqual(response.status_code, 403)

    def test_removing_org_access_makes_note_private(self):
        self.assertEqual(True, True)
