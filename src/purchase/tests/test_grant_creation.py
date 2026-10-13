from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from purchase.models import FundingPool, Grant
from purchase.services.funding_pool_service import FundingPoolService
from purchase.services.grant_creation_service import GrantCreationService
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
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
