import json

from django.test import TestCase

from user.models import UserVerification
from user.serializers import AuthorSerializer, UserEditableSerializer
from user.tests.helpers import create_university, create_user


class UserSerializersTests(TestCase):
    def setUp(self):
        self.user = create_user(first_name="Serializ")
        self.university = create_university()

    def test_author_serializer_succeeds_without_user_or_university(self):
        data = {
            "first_name": "Ray",
            "last_name": "Man",
        }
        serializer = AuthorSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_author_serializer_without_orcid_sends_null(self):
        serializer = AuthorSerializer(self.user.author_profile)
        json_data = json.dumps(serializer.data)
        self.assertIn('"orcid_id": null', json_data)

    def test_user_serializer_is_verified_v2(self):
        UserVerification.objects.create(
            user=self.user,
            status=UserVerification.Status.APPROVED,
        )
        serializer = UserEditableSerializer(self.user)
        self.assertTrue(serializer.data["is_verified_v2"])

    def test_user_serializer_is_not_verified_v2(self):
        UserVerification.objects.create(
            user=self.user,
            status=UserVerification.Status.DECLINED,
        )
        serializer = UserEditableSerializer(self.user)
        self.assertFalse(serializer.data["is_verified_v2"])
