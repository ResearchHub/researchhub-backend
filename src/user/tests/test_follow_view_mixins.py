from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
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

    @patch("feed.views.feed_view_mixin.FeedViewMixin.invalidate_feed_cache_for_user")
    def test_follow_hub_invalidates_cache(self, mock_invalidate):
        """Test that following a hub invalidates the user's feed cache."""
        response = self.client.post(f"/api/hub/{self.hub.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify cache invalidation was called with the user's ID
        mock_invalidate.assert_called_once_with(self.user.id)

    @patch("feed.views.feed_view_mixin.FeedViewMixin.invalidate_feed_cache_for_user")
    def test_follow_user_invalidates_cache(self, mock_invalidate):
        """Test that following a user invalidates the follower's feed cache."""
        response = self.client.post(f"/api/user/{self.target_user.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify cache invalidation was called with the follower's ID
        mock_invalidate.assert_called_once_with(self.user.id)

    @patch("feed.views.feed_view_mixin.FeedViewMixin.invalidate_feed_cache_for_user")
    def test_follow_paper_invalidates_cache(self, mock_invalidate):
        """Test that following a paper invalidates the user's feed cache."""
        response = self.client.post(f"/api/paper/{self.paper.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify cache invalidation was called with the user's ID
        mock_invalidate.assert_called_once_with(self.user.id)

    @patch("feed.views.feed_view_mixin.FeedViewMixin.invalidate_feed_cache_for_user")
    def test_follow_author_invalidates_cache(self, mock_invalidate):
        """Test that following an author invalidates the user's feed cache."""
        author = Author.objects.create(
            first_name="Test",
            last_name="Author",
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        response = self.client.post(f"/api/author/{author.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify cache invalidation was called with the user's ID
        mock_invalidate.assert_called_once_with(self.user.id)

    @patch("feed.views.feed_view_mixin.FeedViewMixin.invalidate_feed_cache_for_user")
    def test_unfollow_hub_invalidates_cache(self, mock_invalidate):
        """Test that unfollowing a hub invalidates the user's feed cache."""
        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=self.hub.id,
        )

        response = self.client.delete(f"/api/hub/{self.hub.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify cache invalidation was called with the user's ID
        mock_invalidate.assert_called_once_with(self.user.id)

    @patch("feed.views.feed_view_mixin.FeedViewMixin.invalidate_feed_cache_for_user")
    def test_unfollow_user_invalidates_cache(self, mock_invalidate):
        """Test that unfollowing a user invalidates the unfollower's feed cache."""
        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.target_user.id,
        )

        response = self.client.delete(f"/api/user/{self.target_user.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify cache invalidation was called with the unfollower's ID
        mock_invalidate.assert_called_once_with(self.user.id)

    @patch("feed.views.feed_view_mixin.FeedViewMixin.invalidate_feed_cache_for_user")
    def test_unfollow_not_following_does_not_invalidate_cache(self, mock_invalidate):
        """Test that unfollowing when not following doesn't invalidate cache."""
        response = self.client.delete(f"/api/user/{self.target_user.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["msg"], "Not following")

        # Cache should not be invalidated since user wasn't following
        mock_invalidate.assert_not_called()

    def test_follow_hub_actually_invalidates_cache(self):
        """Integration test: verify cache is actually cleared when following a hub."""
        # Set up a cache entry for the user's feed
        cache_key = f"feed:following:all:all:{self.user.id}:1-20"
        cache.set(cache_key, {"test": "data"})

        # Verify cache is set
        self.assertIsNotNone(cache.get(cache_key))

        # Follow a hub
        response = self.client.post(f"/api/hub/{self.hub.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify cache is cleared
        self.assertIsNone(cache.get(cache_key))

    def test_unfollow_hub_actually_invalidates_cache(self):
        """Integration test: verify cache is actually cleared when unfollowing a hub."""
        # Create follow first
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=self.hub.id,
        )

        # Set up a cache entry for the user's feed
        cache_key = f"feed:following:all:all:{self.user.id}:1-20"
        cache.set(cache_key, {"test": "data"})

        # Verify cache is set
        self.assertIsNotNone(cache.get(cache_key))

        # Unfollow the hub
        response = self.client.delete(f"/api/hub/{self.hub.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify cache is cleared
        self.assertIsNone(cache.get(cache_key))

    def test_follow_multiple_follows_multiple_hubs(self):
        # Create multiple hubs
        hub1 = Hub.objects.create(name="Hub 1", description="First hub")
        hub2 = Hub.objects.create(name="Hub 2", description="Second hub")
        hub3 = Hub.objects.create(name="Hub 3", description="Third hub")

        # Follow multiple hubs
        response = self.client.post(
            "/api/hub/follow_multiple/",
            {"ids": [hub1.id, hub2.id, hub3.id]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["followed"]), 3)
        self.assertEqual(len(response.data["already_following"]), 0)
        self.assertEqual(len(response.data["not_found"]), 0)

        # Verify follows were created
        self.assertTrue(
            Follow.objects.filter(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=hub1.id,
            ).exists()
        )
        self.assertTrue(
            Follow.objects.filter(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=hub2.id,
            ).exists()
        )
        self.assertTrue(
            Follow.objects.filter(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=hub3.id,
            ).exists()
        )

    def test_unfollow_multiple_unfollows_multiple_hubs(self):
        # Create multiple hubs and follow them
        hub1 = Hub.objects.create(name="Hub 1", description="First hub")
        hub2 = Hub.objects.create(name="Hub 2", description="Second hub")
        hub3 = Hub.objects.create(name="Hub 3", description="Third hub")

        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=hub1.id,
        )
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=hub2.id,
        )
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=hub3.id,
        )

        # Unfollow multiple hubs
        response = self.client.post(
            "/api/hub/unfollow_multiple/",
            {"ids": [hub1.id, hub2.id, hub3.id]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["unfollowed"]), 3)
        self.assertEqual(len(response.data["not_following"]), 0)
        self.assertEqual(len(response.data["not_found"]), 0)

        # Verify follows were deleted
        self.assertFalse(
            Follow.objects.filter(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=hub1.id,
            ).exists()
        )
        self.assertFalse(
            Follow.objects.filter(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=hub2.id,
            ).exists()
        )
        self.assertFalse(
            Follow.objects.filter(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=hub3.id,
            ).exists()
        )

    def test_follow_multiple_skips_not_found_hub_gracefully(self):
        # Create one valid hub
        hub1 = Hub.objects.create(name="Hub 1", description="First hub")

        # Try to follow with a mix of valid and invalid IDs
        invalid_id = 99999
        response = self.client.post(
            "/api/hub/follow_multiple/",
            {"ids": [hub1.id, invalid_id]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["followed"]), 1)
        self.assertEqual(len(response.data["already_following"]), 0)
        self.assertEqual(len(response.data["not_found"]), 1)
        self.assertIn(invalid_id, response.data["not_found"])

        # Verify only the valid hub was followed
        self.assertTrue(
            Follow.objects.filter(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=hub1.id,
            ).exists()
        )

    def test_follow_multiple_marks_already_following(self):
        # Create multiple hubs
        hub1 = Hub.objects.create(name="Hub 1", description="First hub")
        hub2 = Hub.objects.create(name="Hub 2", description="Second hub")
        hub3 = Hub.objects.create(name="Hub 3", description="Third hub")

        # Already follow hub2
        Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Hub),
            object_id=hub2.id,
        )

        # Try to follow all three hubs
        response = self.client.post(
            "/api/hub/follow_multiple/",
            {"ids": [hub1.id, hub2.id, hub3.id]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["followed"]), 2)
        self.assertEqual(len(response.data["already_following"]), 1)
        self.assertEqual(len(response.data["not_found"]), 0)

        # Verify hub2 is in already_following
        already_following_ids = [
            item["id"] for item in response.data["already_following"]
        ]
        self.assertIn(hub2.id, already_following_ids)

        # Verify hub1 and hub3 are in followed
        followed_ids = [item["id"] for item in response.data["followed"]]
        self.assertIn(hub1.id, followed_ids)
        self.assertIn(hub3.id, followed_ids)

        # Verify all three hubs are now followed
        self.assertEqual(
            Follow.objects.filter(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id__in=[hub1.id, hub2.id, hub3.id],
            ).count(),
            3,
        )
