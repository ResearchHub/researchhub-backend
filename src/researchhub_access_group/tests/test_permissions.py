import uuid

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from researchhub_access_group.models import Permission
from researchhub_access_group.permissions import IsOrganizationUser
from user.models import Organization, User


class IsOrganizationUserTest(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

        self.anonymous = AnonymousUser()
        self.user = User.objects.create_user(
            username="user1", password=uuid.uuid4().hex
        )

        self.member = User.objects.create_user(
            username="member1", password=uuid.uuid4().hex
        )
        self.organization = Organization.objects.create(name="org1")
        Permission.objects.create(
            access_type="MEMBER",
            content_type=ContentType.objects.get_for_model(Organization),
            object_id=self.organization.id,
            user=self.member,
        )

    def test_has_object_permission_with_organization_user(self):
        # arrange
        request = self.factory.get("/api/endpoint1/")
        request.user = self.member

        # act
        has_permission = IsOrganizationUser().has_object_permission(
            request, None, self.organization
        )

        # assert
        self.assertTrue(has_permission)

    def test_no_object_permission_without_organization_user(self):
        # arrange
        request = self.factory.get("/api/endpoint1/")
        request.user = self.user

        # act
        has_permission = IsOrganizationUser().has_object_permission(
            request, None, self.organization
        )

        # assert
        self.assertFalse(has_permission)

    def test_no_object_permission_with_anonymous_user(self):
        # arrange
        request = self.factory.get("/api/endpoint1/")
        request.user = self.anonymous

        # act
        has_permission = IsOrganizationUser().has_object_permission(
            request, None, self.organization
        )

        # assert
        self.assertFalse(has_permission)
