from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from user.models import User
from user.serializers import FollowSerializer
from user.tests.helpers import create_user


class FollowSerializerTests(TestCase):
    def setUp(self):
        self.user = create_user(email="follower@test.com")
        self.target_user = create_user(email="target@test.com")
        self.factory = APIRequestFactory()
        self.request = self.factory.get("/")
        self.request.user = self.user

    def test_validate_allowed_content_type(self):
        data = {
            "content_type": "user",
            "object_id": self.target_user.id,
        }
        serializer = FollowSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_validate_disallowed_content_type(self):
        data = {
            "content_type": "permission",  # Not in ALLOWED_FOLLOW_MODELS
            "object_id": 1,
        }
        serializer = FollowSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("content_type", serializer.errors)

    def test_create_follow(self):
        data = {
            "content_type": "user",
            "object_id": self.target_user.id,
        }
        serializer = FollowSerializer(data=data, context={"request": self.request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        follow = serializer.save()

        self.assertEqual(follow.user, self.user)
        self.assertEqual(follow.content_type, ContentType.objects.get_for_model(User))
        self.assertEqual(follow.object_id, self.target_user.id)

    def test_serializer_output_fields(self):
        data = {
            "content_type": "user",
            "object_id": self.target_user.id,
        }
        serializer = FollowSerializer(data=data, context={"request": self.request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        follow = serializer.save()

        serialized_data = FollowSerializer(follow).data
        expected_fields = {
            "id",
            "object_id",
            "created_date",
            "updated_date",
            "type",
        }
        self.assertEqual(set(serialized_data.keys()), expected_fields)

        # Check read-only fields
        self.assertIn("id", serialized_data)
        self.assertIn("created_date", serialized_data)
        self.assertIn("updated_date", serialized_data)

    def test_content_type_slug_field(self):
        data = {
            "content_type": "user",
            "object_id": self.target_user.id,
        }
        serializer = FollowSerializer(data=data, context={"request": self.request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        follow = serializer.save()

        serialized_data = FollowSerializer(follow).data
        self.assertEqual(serialized_data["type"], "USER")
