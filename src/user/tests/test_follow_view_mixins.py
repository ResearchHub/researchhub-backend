from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.viewsets import ModelViewSet

from hub.models import Hub
from paper.models import Paper
from user.models import User
from user.related_models.author_model import Author
from user.related_models.follow_model import Follow
from user.tests.helpers import create_user
from user.views.follow_view_mixins import FollowViewActionMixin


# Create a test viewset that uses the mixin
class TestUserViewSet(FollowViewActionMixin, ModelViewSet):
    queryset = User.objects.all()


class FollowViewActionMixinTests(APITestCase):
    def setUp(self):
        self.user = create_user(
            email="follower@test.com", first_name="Test", last_name="User"
        )
        self.target_user = create_user(
            email="target@test.com", first_name="Target", last_name="User"
        )
        self.client.force_authenticate(user=self.user)
        # Add hub and paper setup
        self.hub = Hub.objects.create(name="Test Hub", description="Test Description")
        self.paper = Paper.objects.create(title="Test Paper", abstract="Test Abstract")

    def test_follow_user(self):
        response = self.client.post(f"/api/user/{self.target_user.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify follow was created
        follow = Follow.objects.get(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.target_user.id,
        )
        self.assertIsNotNone(follow)

    def test_follow_already_following(self):
        # Create follow first
        follow = Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.target_user.id,
        )

        response = self.client.post(f"/api/user/{self.target_user.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], follow.id)

    def test_unfollow_user(self):
        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.target_user.id,
        )

        response = self.client.delete(f"/api/user/{self.target_user.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify follow was deleted
        with self.assertRaises(Follow.DoesNotExist):
            Follow.objects.get(
                user=self.user,
                content_type=ContentType.objects.get_for_model(User),
                object_id=self.target_user.id,
            )

    def test_unfollow_not_following(self):
        response = self.client.delete(f"/api/user/{self.target_user.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["msg"], "Not following")

    def test_is_following_true(self):
        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.target_user.id,
        )

        response = self.client.get(f"/api/user/{self.target_user.id}/is_following/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["following"])
        self.assertIn("follow", response.data)

    def test_is_following_false(self):
        response = self.client.get(f"/api/user/{self.target_user.id}/is_following/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["following"])

    def test_following_list(self):
        # Create multiple follows
        user2 = create_user(email="user2@test.com")
        user3 = create_user(email="user3@test.com")

        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=user2.id,
        )
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=user3.id,
        )

        response = self.client.get("/api/user/following/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_follow_hub(self):
        response = self.client.post(f"/api/hub/{self.hub.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify follow was created
        follow = Follow.objects.get(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=self.hub.id,
        )
        self.assertIsNotNone(follow)

    def test_unfollow_hub(self):
        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=self.hub.id,
        )

        response = self.client.delete(f"/api/hub/{self.hub.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify follow was deleted
        with self.assertRaises(Follow.DoesNotExist):
            Follow.objects.get(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=self.hub.id,
            )

    def test_is_following_hub(self):
        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=self.hub.id,
        )

        response = self.client.get(f"/api/hub/{self.hub.id}/is_following/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["following"])
        self.assertIn("follow", response.data)

    def test_follow_paper(self):
        response = self.client.post(f"/api/paper/{self.paper.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify follow was created
        follow = Follow.objects.get(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
        )
        self.assertIsNotNone(follow)

    def test_unfollow_paper(self):
        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
        )

        response = self.client.delete(f"/api/paper/{self.paper.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify follow was deleted
        with self.assertRaises(Follow.DoesNotExist):
            Follow.objects.get(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Paper),
                object_id=self.paper.id,
            )

    def test_is_following_paper(self):
        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
        )

        response = self.client.get(f"/api/paper/{self.paper.id}/is_following/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["following"])
        self.assertIn("follow", response.data)

    def test_follow_author(self):
        # Create an author
        self.author = Author.objects.create(
            first_name="Test",
            last_name="Author",
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        response = self.client.post(f"/api/author/{self.author.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify follow was created
        follow = Follow.objects.get(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Author),
            object_id=self.author.id,
        )
        self.assertIsNotNone(follow)

    def test_follow_author_already_following(self):
        # Create an author
        self.author = Author.objects.create(
            first_name="Test",
            last_name="Author",
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        # Create follow first
        follow = Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Author),
            object_id=self.author.id,
        )

        response = self.client.post(f"/api/author/{self.author.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], follow.id)

    def test_unfollow_author(self):
        # Create an author
        self.author = Author.objects.create(
            first_name="Test",
            last_name="Author",
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Author),
            object_id=self.author.id,
        )

        response = self.client.delete(f"/api/author/{self.author.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify follow was deleted
        with self.assertRaises(Follow.DoesNotExist):
            Follow.objects.get(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Author),
                object_id=self.author.id,
            )

    def test_unfollow_author_not_following(self):
        # Create an author
        self.author = Author.objects.create(
            first_name="Test",
            last_name="Author",
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        response = self.client.delete(f"/api/author/{self.author.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["msg"], "Not following")

    def test_is_following_author_true(self):
        # Create an author
        self.author = Author.objects.create(
            first_name="Test",
            last_name="Author",
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Author),
            object_id=self.author.id,
        )

        response = self.client.get(f"/api/author/{self.author.id}/is_following/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["following"])
        self.assertIn("follow", response.data)

    def test_is_following_author_false(self):
        # Create an author
        self.author = Author.objects.create(
            first_name="Test",
            last_name="Author",
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        response = self.client.get(f"/api/author/{self.author.id}/is_following/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["following"])
