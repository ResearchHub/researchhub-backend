from rest_framework.test import APITestCase
from allauth.utils import (
    get_user_model,
)
from researchhub_document.models import (
    ResearchhubUnifiedDocument
)
from researchhub_access_group.models import Permission
from django.contrib.contenttypes.models import ContentType
from note.models import (
    Note
)
from user.models import Organization


unified_doc_content_type = ContentType.objects.get_for_model(
    ResearchhubUnifiedDocument
)
organization_content_type = ContentType.objects.get_for_model(Organization)


class NoteTests(APITestCase):
    def setUp(self):
        # Create + auth user
        username = 'test@researchhub_test.com'
        password = 'password'
        self.user = get_user_model().objects.create_user(
            username=username,
            password=password,
            email=username
        )
        self.client.force_authenticate(self.user)

        # Create org
        response = self.client.post('/api/organization/', {'name': 'some org'})
        self.org = response.data

    def test_create_workspace_note(self):
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        created_note = response.data
        self.assertEqual(created_note['access'], 'WORKSPACE')

    def test_create_private_note(self):
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'PRIVATE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        created_note = response.data
        self.assertEqual(created_note['access'], 'PRIVATE')

    def test_delete_private_note(self):
        created_response = self.client.post(
            '/api/note/',
            {
                'grouping': 'PRIVATE',
                'organization_slug': self.org['slug'],
                'title': 'TO BE DELETED'
            }
        )
        created_note = created_response.data
        response = self.client.post(f"/api/note/{created_note['id']}/delete/")
        self.assertEqual(response.status_code, 200)

    def test_cannot_create_shared_note_manually(self):
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'SHARED',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        created_note = response.data

        # NOTE: Should only be able to created SHARED note by inviting useres
        self.assertNotEqual(created_note['access'], 'SHARED')

    def test_note_editor_cannot_invite_others(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        note = response.data

        # Create another user
        editor_user = get_user_model().objects.create_user(
            username='editor@researchhub_test.com',
            password='password',
            email='editor@researchhub_test.com'
        )

        # Add permission to user
        perms = Permission.objects.create(
            access_type='EDITOR',
            content_type=unified_doc_content_type,
            object_id=note['unified_document']['id'],
            user=editor_user
        )

        # Authenticate user and invite
        self.client.force_authenticate(editor_user)
        response = self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                'access_type': 'ADMIN',
                'email': 'invited@researchhub_test.com',
                'expire': 10080
            }
        )

        # Get new permissions
        self.assertEqual(response.status_code, 403)

    def test_note_editor_can_update_contents(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        note = response.data

        # Create another user
        editor_user = get_user_model().objects.create_user(
            username='editor@researchhub_test.com',
            password='password',
            email='editor@researchhub_test.com'
        )

        # Add permission to user
        perms = Permission.objects.create(
            access_type='EDITOR',
            content_type=unified_doc_content_type,
            object_id=note['unified_document']['id'],
            user=editor_user
        )

        # Update title
        response = self.client.patch(
            f"/api/note/{note['id']}/",
            {'title': 'some title'}
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note['title'], 'some title')

        # Update body
        response = self.client.post(
            '/api/note_content/',
            {'full_src': 'updated body', 'note': note['id'], 'plain_text': ''}
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note['latest_version']['src'], 'updated body')

    def test_note_viewer_cannot_update_contents(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'original title'
            }
        )
        note = response.data

        # Create another user
        viewer_user = get_user_model().objects.create_user(
            username='editor@researchhub_test.com',
            password='password',
            email='editor@researchhub_test.com'
        )

        # Add permission to user
        perms = Permission.objects.create(
            access_type='VIEWER',
            content_type=unified_doc_content_type,
            object_id=note['unified_document']['id'],
            user=viewer_user
        )

        # Authenticate as viewer
        self.client.force_authenticate(viewer_user)

        # Update title
        response = self.client.patch(
            f"/api/note/{note['id']}/",
            {'title': 'updated title'}
        )
        self.assertEqual(response.status_code, 403)

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note['title'], 'original title')

        # Update body
        response = self.client.post(
            '/api/note_content/',
            {'full_src': 'updated body', 'note': note['id'], 'plain_text': ''}
        )
        self.assertEqual(response.status_code, 403)

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note['latest_version'], None)

    def test_note_viewer_cannot_invite_others(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        note = response.data

        # Create another user
        invited_viewer = get_user_model().objects.create_user(
            username='editor@researchhub_test.com',
            password='password',
            email='editor@researchhub_test.com'
        )

        # Add permission to user
        perms = Permission.objects.create(
            access_type='VIEWER',
            content_type=unified_doc_content_type,
            object_id=note['unified_document']['id'],
            user=invited_viewer
        )

        # Authenticate user and invite
        self.client.force_authenticate(invited_viewer)
        response = self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                'access_type': 'ADMIN',
                'email': 'invited@researchhub_test.com',
                'expire': 10080
            }
        )

        # Get new permissions
        self.assertEqual(response.status_code, 403)

    def test_note_admin_can_invite_others(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        note = response.data

        # Create another user
        invited_note_admin = get_user_model().objects.create_user(
            username='admin@researchhub_test.com',
            password='password',
            email='admin@researchhub_test.com'
        )

        # Add permission to user
        perms = Permission.objects.create(
            access_type='ADMIN',
            content_type=unified_doc_content_type,
            object_id=note['unified_document']['id'],
            user=invited_note_admin
        )

        # Authenticate user and invite
        self.client.force_authenticate(invited_note_admin)
        response = self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                'access_type': 'ADMIN',
                'email': 'invited@researchhub_test.com',
                'expire': 10080
            }
        )

        # Get new permissions
        self.assertEqual(response.status_code, 200)
        note = Note.objects.get(id=note['id'])
        p = note.permissions.get(user=invited_note_admin.id)
        self.assertTrue(p)

    def test_invited_user_cannot_create_org_notes(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        note = response.data

        # Create another user
        invited_note_admin = get_user_model().objects.create_user(
            username='admin@researchhub_test.com',
            password='password',
            email='admin@researchhub_test.com'
        )

        # Add permission to user
        perms = Permission.objects.create(
            access_type='ADMIN',
            content_type=unified_doc_content_type,
            object_id=note['unified_document']['id'],
            user=invited_note_admin
        )

        # Authenticate user and create org note
        self.client.force_authenticate(invited_note_admin)
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )

        self.assertEqual(response.status_code, 403)

    def test_removing_note_org_access_makes_note_private(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        note = response.data

        # Remove org permission
        self.client.delete(
            f"/api/note/{note['id']}/remove_permission/",
            {'organization': self.org['id']}
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data

        self.assertEqual(note['access'], 'PRIVATE')

    def test_sharing_private_note_move_to_shared_context(self):
        # create private note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'PRIVATE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        note = response.data

        # Invite another user
        self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                'access_type': 'ADMIN',
                'email': 'invited@researchhub_test.com',
                'expire': 10080
            }
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data

        self.assertEqual(note['access'], 'SHARED')

    def test_removing_invited_user_from_shared_note_moves_note_to_private_context(self):
        # create private note
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "PRIVATE",
                "organization_slug": self.org["slug"],
                "title": "TEST"
            }
        )
        note = response.data

        # Invite another user
        self.client.post(
            f"/api/note/{note['id']}/invite_user/",
            {
                'access_type': 'ADMIN',
                'email': 'invited@researchhub_test.com',
                'expire': 10080
            }
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note['access'], 'SHARED')

        # Remove user access
        self.client.patch(
            f"/api/note/{note['id']}/remove_invited_user/",
            {'email': 'invited@researchhub_test.com'}
        )

        # Re-fetch note
        response = self.client.get(f"/api/note/{note['id']}/")
        note = response.data
        self.assertEqual(note['access'], 'PRIVATE')

    def test_user_with_both_viewer_and_org_permission_able_to_edit_note(self):
        # create note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'TEST'
            }
        )
        note = response.data

        # Create viewer user
        viewer_user = get_user_model().objects.create_user(
            username='user_b@researchhub_test.com',
            password='password',
            email='user_b@researchhub_test.com'
        )

        # Add permission to user
        perms = Permission.objects.create(
            access_type='VIEWER',
            content_type=unified_doc_content_type,
            object_id=note['unified_document']['id'],
            user=viewer_user
        )

        # Upgrade user to org member
        perms = Permission.objects.create(
            access_type='MEMBER',
            content_type=organization_content_type,
            object_id=self.org['id'],
            user=viewer_user
        )

        # authenticate and update note
        self.client.force_authenticate(viewer_user)
        response = self.client.patch(
            f"/api/note/{note['id']}/",
            {'title': 'some title'}
        )

        # refetch note
        response = self.client.patch(f"/api/note/{note['id']}/")
        self.assertEqual(response.data['title'], 'some title')

    def test_note_admin_can_make_private(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'original title'
            }
        )
        note = response.data

        # Create another user
        admin_user = get_user_model().objects.create_user(
            username='admin@researchhub_test.com',
            password='password',
            email='admin@researchhub_test.com'
        )

        # Add permission to user
        perms = Permission.objects.create(
            access_type='ADMIN',
            content_type=unified_doc_content_type,
            object_id=note['unified_document']['id'],
            user=admin_user
        )

        # Authenticate as viewer
        self.client.force_authenticate(admin_user)

        # Make Private
        response = self.client.post(f"/api/note/{note['id']}/make_private/")
        self.assertEqual(response.data["access"], "PRIVATE")

    def test_note_editor_cannot_make_private(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'original title'
            }
        )
        note = response.data

        # Create another user
        editor_user = get_user_model().objects.create_user(
            username='editor@researchhub_test.com',
            password='password',
            email='editor@researchhub_test.com'
        )

        # Add permission to user
        perms = Permission.objects.create(
            access_type='EDITOR',
            content_type=unified_doc_content_type,
            object_id=note['unified_document']['id'],
            user=editor_user
        )

        # Authenticate as viewer
        self.client.force_authenticate(editor_user)

        # Make Private
        response = self.client.post(f"/api/note/{note['id']}/make_private/")
        self.assertEqual(response.status_code, 403)

    def test_org_member_can_make_private(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'original title'
            }
        )
        note = response.data

        # Create another user
        member_user = get_user_model().objects.create_user(
            username='member@researchhub_test.com',
            password='password',
            email='member@researchhub_test.com'
        )

        # Add second user
        perms = Permission.objects.create(
            access_type='MEMBER',
            content_type=organization_content_type,
            object_id=self.org['id'],
            user=member_user
        )

        # Authenticate as viewer
        self.client.force_authenticate(member_user)

        # Make Private
        response = self.client.post(f"/api/note/{note['id']}/make_private/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['access'], 'PRIVATE')

    def test_org_member_can_remove_workspace_note(self):
        # Create workspace note
        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'WORKSPACE',
                'organization_slug': self.org['slug'],
                'title': 'some note to be deleted'
            }
        )
        note = response.data

        # Create another user
        member_user = get_user_model().objects.create_user(
            username='member@researchhub_test.com',
            password='password',
            email='member@researchhub_test.com'
        )

        # Add user
        perms = Permission.objects.create(
            access_type='MEMBER',
            content_type=organization_content_type,
            object_id=self.org['id'],
            user=member_user
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
        self.assertEqual(response.data['count'], 0)

    def test_org_member_making_private_note(self):
        """
        Tests creating a private note, moving it to the workspace,
        and having another user set the note back to private
        """
        # Create a user
        alice = get_user_model().objects.create_user(
            username='alice@researchhub_test.com',
            password='password',
            email='alice@researchhub_test.com'
        )
        alice_org = alice.organization

        self.client.force_authenticate(alice)

        bob = get_user_model().objects.create_user(
            username='bob@researchhub_test.com',
            password='password',
            email='bob@researchhub_test.com'
        )
        # Add Bob as Admin to Alice Org
        content_type = ContentType.objects.get_for_model(Organization)
        Permission.objects.create(
            access_type='ADMIN',
            content_type=content_type,
            object_id=alice_org.id,
            user=bob
        )

        response = self.client.post(
            '/api/note/',
            {
                'grouping': 'PRIVATE',
                'organization_slug': alice_org.slug,
                'title': 'private to workspace to private'
            }
        )
        note = response.data

        # Change note to workspace
        perm_response = self.client.patch(
            f"/api/note/{note['id']}/update_permissions/",
            {
                'access_type': 'ADMIN',
                'organization': alice_org.id,
            }
        )
        updated_note = self.client.get(
            f"/api/note/{note['id']}/"
        )
        self.assertEqual(updated_note.data['access'], 'WORKSPACE')

        # Switch to Bob
        self.client.force_authenticate(bob)

        # Make the note private
        response = self.client.post(
            f"/api/note/{note['id']}/make_private/"
        )
        self.assertEqual(response.data['access'], 'PRIVATE')

        bobs_notes_from_alice_org = self.client.get(
            f'/api/organization/{alice_org.slug}/get_organization_notes/'
        )
        self.assertEqual(
            bobs_notes_from_alice_org.data['results'][0]['access'],
            'PRIVATE'
        )

        # Switch to Alice
        self.client.force_authenticate(alice)

        alice_notes_from_alice_org = self.client.get(
            f'/api/organization/{alice_org.slug}/get_organization_notes/'
        )

        self.assertEqual(
            alice_notes_from_alice_org.data['count'],
            0
        )

        response = self.client.get(
            f"/api/note/{note['id']}/"
        )
        self.assertEqual(response.status_code, 403)

    def test_user_can_delete_own_org_templates(self):
        # Create template
        response = self.client.post(
            '/api/note_template/',
            {
                'full_src': 'test',
                'is_default': False,
                'organization': self.org['id'],
                'name': 'NON-DEFAULT TEMPLATE'
            }
        )
        template = response.data

        # Delete template
        delete_response = self.client.post(f"/api/note_template/{template['id']}/delete/")

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.data['is_removed'], True)

    def test_user_cannot_delete_default_template(self):
        # Create template
        response = self.client.post(
            '/api/note_template/',
            {
                'full_src': 'test',
                'is_default': True,
                'organization': self.org['id'],
                'name': 'DEFAULT TEMPLATE'
            }
        )
        template = response.data

        # Delete template
        delete_response = self.client.post(f"/api/note_template/{template['id']}/delete/")

        self.assertEqual(delete_response.status_code, 403)
        self.assertEqual(delete_response.data['is_removed'], False)
