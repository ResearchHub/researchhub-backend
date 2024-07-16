import json

from django.test import TestCase

from hub.models import Hub
from reputation.models import Score
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

    def test_author_serializer_with_reputation(self):
        hub1 = Hub.objects.create(name="Hub 1")
        hub2 = Hub.objects.create(name="Hub 2")
        Score.objects.create(
            author=self.user.author_profile,
            hub=hub1,
            score=900,
        )

        Score.objects.create(
            author=self.user.author_profile,
            hub=hub2,
            score=1000,
        )

        serializer = AuthorSerializer(self.user.author_profile)
        self.assertEqual(serializer.data["reputation_v2"]["score"], 1000)
        self.assertEqual(serializer.data["reputation_list"][0]["score"], 1000)
        self.assertEqual(serializer.data["reputation_list"][1]["score"], 900)

    def test_user_serializer_is_verified(self):
        self.user.is_verified = True
        serializer = UserEditableSerializer(self.user)
        self.assertTrue(serializer.data["is_verified"])

    def test_user_serializer_is_not_verified(self):
        self.user.is_verified = False
        serializer = UserEditableSerializer(self.user)
        self.assertFalse(serializer.data["is_verified"])

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
