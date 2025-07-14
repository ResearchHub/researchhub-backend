from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext, override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from hub.models import Hub
from researchhub_access_group.constants import EDITOR, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from user.models import Author, User


class ResearchhubPostRecursiveQueryTest(TransactionTestCase):
    """Test case to reproduce the recursive query issue with permissions."""

    def setUp(self):
        # Create test client
        self.client = APIClient()

        # Create test users
        self.users = []
        self.authors = []

        # Create 5 users with authors - using get_or_create to avoid conflicts
        for i in range(5):
            user, _ = User.objects.get_or_create(
                username=f"testuser{i}",
                defaults={
                    "email": f"testuser{i}@example.com",
                    "password": "testpass123",
                },
            )
            author, _ = Author.objects.get_or_create(
                user=user,
                defaults={"first_name": f"Test{i}", "last_name": f"Author{i}"},
            )
            self.users.append(user)
            self.authors.append(author)

        # Create a hub
        self.hub = Hub.objects.create(
            name="Test Hub", description="Test hub for query testing"
        )

        # Create unified document
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", is_public=True
        )
        self.unified_doc.hubs.add(self.hub)

        # Create ResearchHub post with multiple authors
        self.post = ResearchhubPost.objects.create(
            title="Test Post with Multiple Authors",
            renderable_text="This is a test post to reproduce the query issue.",
            created_by=self.users[0],
            unified_document=self.unified_doc,
            document_type="DISCUSSION",
        )

        # Add all authors to the post
        self.post.authors.set(self.authors)

        # Add permissions for some users (this will trigger permission queries)
        hub_content_type = ContentType.objects.get_for_model(Hub)

        # Give editor permissions to users 0, 1, and 2
        for i in range(3):
            Permission.objects.create(
                user=self.users[i],
                content_type=hub_content_type,
                object_id=self.hub.id,
                access_type=EDITOR,
            )

        # Give viewer permissions to users 3 and 4
        for i in range(3, 5):
            Permission.objects.create(
                user=self.users[i],
                content_type=hub_content_type,
                object_id=self.hub.id,
                access_type=VIEWER,
            )

    def test_post_retrieval_query_count(self):
        """Test that retrieving a post doesn't cause excessive permission queries."""

        # Login as one of the users
        self.client.force_authenticate(user=self.users[0])

        # Track queries
        with CaptureQueriesContext(connection) as context:
            response = self.client.get(f"/api/posts/{self.post.id}/")

        # Print query information
        print(f"\nTotal queries executed: {len(context.captured_queries)}")

        # Count permission-related queries
        permission_queries = [
            q
            for q in context.captured_queries
            if "researchhub_access_group_permission" in q["sql"]
        ]

        print(f"Permission queries: {len(permission_queries)}")

        # Print each permission query
        for i, query in enumerate(permission_queries):
            print(f"\nPermission Query {i+1}:")
            print(
                query["sql"][:200] + "..." if len(query["sql"]) > 200 else query["sql"]
            )

        # Assert response is successful
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check if we have the N+1 query problem
        # We have 5 authors, so we shouldn't have more than 5-6 permission queries
        self.assertLess(
            len(permission_queries),
            10,
            f"Too many permission queries: {len(permission_queries)}. Possible N+1 query problem.",
        )

    def test_multiple_posts_with_shared_authors(self):
        """Test retrieving multiple posts that share authors."""

        # Create another post with some of the same authors
        post2 = ResearchhubPost.objects.create(
            title="Second Test Post",
            renderable_text="Another test post.",
            created_by=self.users[1],
            unified_document=self.unified_doc,
            document_type="DISCUSSION",
        )
        post2.authors.set(self.authors[:3])  # Only first 3 authors

        # Login as one of the users
        self.client.force_authenticate(user=self.users[0])

        # Track queries for listing posts
        with CaptureQueriesContext(connection) as context:
            response = self.client.get("/api/posts/")

        permission_queries = [
            q
            for q in context.captured_queries
            if "researchhub_access_group_permission" in q["sql"]
        ]

        print(f"\nList view - Total queries: {len(context.captured_queries)}")
        print(f"List view - Permission queries: {len(permission_queries)}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_permission_prefetch_optimization(self):
        """Test if we can optimize permission queries using prefetch_related."""

        # This test is to verify if adding prefetch_related helps
        from django.db.models import Prefetch

        # Get the post with prefetched data
        post_with_prefetch = (
            ResearchhubPost.objects.select_related("created_by", "unified_document")
            .prefetch_related(
                Prefetch(
                    "authors",
                    queryset=Author.objects.select_related("user").prefetch_related(
                        "user__permissions"
                    ),
                )
            )
            .get(id=self.post.id)
        )

        # Simulate serialization with prefetched data
        with CaptureQueriesContext(connection) as context:
            # Access authors and their permissions
            for author in post_with_prefetch.authors.all():
                if author.user:
                    # This should not trigger additional queries
                    permissions = list(author.user.permissions.all())

        print(
            f"\nPrefetch test - Queries after prefetch: {len(context.captured_queries)}"
        )

        # Should be minimal queries since we prefetched
        self.assertLess(len(context.captured_queries), 5)
