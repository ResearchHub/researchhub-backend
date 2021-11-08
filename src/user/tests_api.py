from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from researchhub_access_group.models import Permission
from django.contrib.contenttypes.models import ContentType
from user.models import Organization
from user.related_models.user_model import User
from allauth.utils import (
    get_user_model,
)

class OrganizationTests(APITestCase):
    def setUp(self):
        # Create + auth user
        self.admin_user = get_user_model().objects.create_user(username="admin@example.com", password="password", email="admin@example.com")
        self.second_user = get_user_model().objects.create_user(username="test@example.com", password="password", email="test@example.com")
        self.client.force_authenticate(self.admin_user)

        # Create org
        response = self.client.post("/api/organization/", {"name": "some org"})
        self.org = response.data

        # Add second user
        perms = Permission.objects.create(
            access_type="ADMIN",
            content_type=ContentType.objects.get_for_model(Organization),
            object_id=self.org["id"],
            user=self.second_user
        )

    def test_get_organization_users(self):
        response = self.client.get(f'/api/organization/{self.org["id"]}/get_organization_users/')

        print(response.data['user_count'])
        self.assertEqual(response.data['user_count'], 2)

