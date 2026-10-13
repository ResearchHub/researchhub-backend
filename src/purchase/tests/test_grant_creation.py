from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APITestCase

from note.services.note_creation_service import NoteCreationService
from purchase.models import FundingPool, Grant
from purchase.services.funding_pool_service import FundingPoolService
from purchase.services.grant_creation_service import GrantCreationService
from researchhub_access_group.constants import MEMBER
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.permissions import HasDocumentEditingPermission
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
from user.models import Organization
from user.tests.helpers import create_random_authenticated_user


class GrantCreationTests(APITestCase):
    def setUp(self):
        self.owner = create_random_authenticated_user("grant_creation_owner")
        self.attacker = create_random_authenticated_user("grant_creation_attacker")
        self.moderator = create_random_authenticated_user(
            "grant_creation_moderator", moderator=True
        )
        self.grant_data = {
            "amount": "1000.00",
            "currency": "USD",
            "description": "Research grant",
        }

    def test_other_users_cannot_attach_grants_to_public_posts(self):
        for document_type in (DISCUSSION, GRANT):
            for identifier in ("post_id", "unified_document_id"):
                with self.subTest(document_type=document_type, identifier=identifier):
                    # Arrange
                    post = create_post(
                        created_by=self.owner, document_type=document_type
                    )
                    target_id = (
                        post.pk if identifier == "post_id" else post.unified_document_id
                    )
                    self.client.force_authenticate(self.attacker)
                    self.assertTrue(
                        ResearchhubPost.objects.visible_to(None)
                        .filter(pk=post.pk)
                        .exists()
                    )

                    # Act
                    response = self.client.post(
                        "/api/grant/",
                        {**self.grant_data, identifier: target_id},
                    )

                    # Assert
                    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                    self.assertFalse(
                        Grant.objects.filter(
                            unified_document=post.unified_document
                        ).exists()
                    )
                    self.assertFalse(FundingPool.objects.exists())
                    self.assertTrue(
                        ResearchhubPost.objects.visible_to(None)
                        .filter(pk=post.pk)
                        .exists()
                    )
                    self.assertTrue(
                        ResearchhubPost.objects.visible_to(self.attacker)
                        .filter(pk=post.pk)
                        .exists()
                    )

    def test_author_can_create_grant_with_either_identifier(self):
        for identifier in ("post_id", "unified_document_id"):
            with self.subTest(identifier=identifier):
                # Arrange
                post = create_post(created_by=self.owner, document_type=GRANT)
                target_id = (
                    post.pk if identifier == "post_id" else post.unified_document_id
                )
                self.client.force_authenticate(self.owner)

                # Act
                response = self.client.post(
                    "/api/grant/",
                    {
                        **self.grant_data,
                        identifier: target_id,
                        "contact_ids": [self.owner.pk],
                        "application_visibility": Grant.APPLICATION_VISIBILITY_PRIVATE,
                    },
                )

                # Assert
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                grant = Grant.objects.get(pk=response.data["id"])
                self.assertEqual(grant.created_by, self.owner)
                self.assertEqual(grant.status, Grant.PENDING)
                self.assertEqual(list(grant.contacts.all()), [self.owner])
                self.assertEqual(
                    grant.application_visibility, Grant.APPLICATION_VISIBILITY_PRIVATE
                )
                self.assertTrue(FundingPool.objects.filter(grant=grant).exists())

    def test_moderator_can_create_grant_for_another_author(self):
        # Arrange
        post = create_post(created_by=self.owner, document_type=GRANT)
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            "/api/grant/",
            {**self.grant_data, "post_id": post.pk},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Grant.objects.get(pk=response.data["id"]).created_by, self.moderator
        )

    def test_duplicate_grant_does_not_hide_existing_open_grant(self):
        # Arrange
        post = create_post(created_by=self.owner, document_type=GRANT)
        original = GrantCreationService().create_grant(
            created_by=self.owner,
            unified_document=post.unified_document,
            **self.grant_data,
        )
        original.status = Grant.OPEN
        original.save(update_fields=["status"])
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.post(
            "/api/grant/", {**self.grant_data, "post_id": post.pk}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            Grant.objects.filter(unified_document=post.unified_document).count(), 1
        )
        self.assertEqual(FundingPool.objects.filter(grant=original).count(), 1)
        self.assertTrue(
            ResearchhubPost.objects.visible_to(None).filter(pk=post.pk).exists()
        )

    def test_author_can_attach_grant_to_preregistration(self):
        # Arrange
        post = create_post(created_by=self.owner, document_type=PREREGISTRATION)
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.post(
            "/api/grant/", {**self.grant_data, "post_id": post.pk}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Grant.objects.get(pk=response.data["id"]).unified_document,
            post.unified_document,
        )

    def test_document_without_authored_post_is_rejected(self):
        # Arrange
        document = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.post(
            "/api/grant/", {**self.grant_data, "unified_document_id": document.pk}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Grant.objects.filter(unified_document=document).exists())

    def test_organization_member_can_create_grant_for_note_backed_post(self):
        # Arrange
        self._add_organization_member()
        self.client.force_authenticate(self.attacker)

        for identifier in ("post_id", "unified_document_id"):
            with self.subTest(identifier=identifier):
                post = self._create_note_backed_post()
                target_id = (
                    post.pk if identifier == "post_id" else post.unified_document_id
                )

                # Act
                response = self.client.post(
                    "/api/grant/", {**self.grant_data, identifier: target_id}
                )

                # Assert
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                grant = Grant.objects.get(pk=response.data["id"])
                self.assertEqual(grant.created_by, self.attacker)
                self.assertEqual(grant.unified_document, post.unified_document)
                self.assertTrue(FundingPool.objects.filter(grant=grant).exists())

    def test_non_member_cannot_create_grant_for_note_backed_post(self):
        # Arrange
        post = self._create_note_backed_post()
        self.client.force_authenticate(self.attacker)

        # Act
        response = self.client.post(
            "/api/grant/", {**self.grant_data, "post_id": post.pk}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            Grant.objects.filter(unified_document=post.unified_document).exists()
        )

    def test_organization_membership_does_not_authorize_posts_without_a_note(self):
        # Arrange
        self._add_organization_member()
        post = create_post(created_by=self.owner, document_type=GRANT)
        self.client.force_authenticate(self.attacker)

        # Act
        response = self.client.post(
            "/api/grant/", {**self.grant_data, "post_id": post.pk}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            Grant.objects.filter(unified_document=post.unified_document).exists()
        )

    def test_note_without_organization_does_not_allow_unrelated_grant_creator(self):
        # Arrange
        post = self._create_note_backed_post()
        post.note.organization = None
        post.note.save(update_fields=["organization"])
        self.client.force_authenticate(self.attacker)

        # Act
        response = self.client.post(
            "/api/grant/", {**self.grant_data, "post_id": post.pk}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            Grant.objects.filter(unified_document=post.unified_document).exists()
        )

    def test_service_requires_an_authenticated_grant_creator(self):
        # Arrange
        post = create_post(created_by=self.owner, document_type=GRANT)
        service = GrantCreationService()

        # Act
        with self.assertRaises(PermissionDenied):
            service.create_grant(
                created_by=None,
                unified_document=post.unified_document,
                **self.grant_data,
            )

        # Assert
        self.assertFalse(Grant.objects.exists())
        self.assertFalse(FundingPool.objects.exists())

    def test_editing_permission_rejects_a_missing_user(self):
        # Arrange
        post = create_post(created_by=self.owner, document_type=GRANT)
        permission = HasDocumentEditingPermission()

        # Act
        allowed = permission.can_edit_post(post, None)

        # Assert
        self.assertFalse(allowed)

    def _create_note_backed_post(self):
        note = NoteCreationService().create_private_note(
            created_by=self.owner, title="Organization grant draft"
        )
        post = create_post(created_by=self.owner, document_type=GRANT)
        post.note = note
        post.save(update_fields=["note"])
        return post

    def _add_organization_member(self):
        Permission.objects.create(
            content_type=ContentType.objects.get_for_model(Organization),
            object_id=self.owner.organization.pk,
            user=self.attacker,
            access_type=MEMBER,
        )

    def test_pool_creation_failure_rolls_back_grant(self):
        # Arrange
        post = create_post(created_by=self.owner, document_type=GRANT)
        pool_service = FundingPoolService()
        service = GrantCreationService(funding_pool_service=pool_service)

        # Act
        with (
            patch.object(
                pool_service,
                "create_pool_for_grant",
                side_effect=RuntimeError("Failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.create_grant(
                created_by=self.owner,
                unified_document=post.unified_document,
                **self.grant_data,
            )

        # Assert
        self.assertFalse(
            Grant.objects.filter(unified_document=post.unified_document).exists()
        )
        self.assertFalse(FundingPool.objects.exists())
