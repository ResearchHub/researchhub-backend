import json

from django.test import TestCase

from user.serializers import AuthorSerializer
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

    def test_author_serializer_linkedin_data(self):
        data = {
            "first_name": "Ray",
            "last_name": "Man",
            "linkedin_data": {
                "sub": "Sub",
                "name": "Name",
                "email": "name@email.com",
                "locale": {
                    "country": "US",
                    "language": "en",
                },
                "picture": "img.jpg",
                "given_name": "Given",
                "family_name": "Family",
                "email_verified": True,
            },
        }
        serializer = AuthorSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)

        author = serializer.save()
        self.assertEqual(author.first_name, data["first_name"])
        self.assertEqual(author.last_name, data["last_name"])
        self.assertEqual(
            author.linkedin_data,
            {
                "sub": "Sub",
            },
        )

    def test_author_serializer_without_linkedin_data_returns_none(self):
        data = {
            "first_name": "Ray",
            "last_name": "Man",
        }
        serializer = AuthorSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)

        author = serializer.save()
        self.assertEqual(author.first_name, data["first_name"])
        self.assertEqual(author.last_name, data["last_name"])
        self.assertEqual(author.linkedin_data, None)

    def test_author_serializer_without_orcid_sends_null(self):
        serializer = AuthorSerializer(self.user.author_profile)
        json_data = json.dumps(serializer.data)
        self.assertIn('"orcid_id": null', json_data)
