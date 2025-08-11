from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from analytics.amplitude import Amplitude

User = get_user_model()


class AmplitudeTests(TestCase):
    def setUp(self):
        self.amplitude = Amplitude()

    def test_build_user_properties_anonymous_user(self):
        """Test _build_user_properties with an anonymous user."""
        # Arrange
        anonymous_user = AnonymousUser()

        # Act
        user_id, user_properties = self.amplitude._build_user_properties(anonymous_user)

        # Assert
        self.assertEqual(user_id, "")
        self.assertEqual(user_properties["email"], "")
        self.assertEqual(user_properties["first_name"], "Anonymous")
        self.assertEqual(user_properties["last_name"], "Anonymous")
        self.assertEqual(user_properties["reputation"], 0)
        self.assertFalse(user_properties["is_suspended"])
        self.assertFalse(user_properties["probable_spammer"])
        self.assertEqual(user_properties["invited_by_id"], 0)
        self.assertFalse(user_properties["is_hub_editor"])
        self.assertFalse(user_properties["is_verified"])

    def test_build_user_properties_authenticated_user(self):
        """Test _build_user_properties with an authenticated user."""
        # Arrange
        user = User.objects.create(
            first_name="firstName1",
            last_name="lastName1",
            email="email1@researchhub.com",
        )
        user.reputation = 500
        user.is_suspended = False
        user.probable_spammer = False
        user.save()

        # Act
        user_id, user_properties = self.amplitude._build_user_properties(user)

        # Assert
        self.assertEqual(user_id, f"{user.id:0>6}")
        self.assertEqual(user_properties["email"], "email1@researchhub.com")
        self.assertEqual(user_properties["first_name"], "firstName1")
        self.assertEqual(user_properties["last_name"], "lastName1")
        self.assertEqual(user_properties["reputation"], 500)
        self.assertFalse(user_properties["is_suspended"])
        self.assertFalse(user_properties["probable_spammer"])
        self.assertIsNone(user_properties["invited_by_id"])
        self.assertFalse(user_properties["is_hub_editor"])
        self.assertFalse(user_properties["is_verified"])
