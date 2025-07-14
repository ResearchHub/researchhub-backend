"""Simple test to reproduce the N+1 query issue with permissions."""

from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from hub.models import Hub
from researchhub_access_group.constants import EDITOR
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from user.models import Author, User
from user.serializers import AuthorSerializer


class SimpleRecursiveQueryTest(TestCase):
    """Test to demonstrate N+1 query issue in AuthorSerializer."""

    def setUp(self):
        """Create test data."""
        # Create 5 test users with authors
        self.authors = []
        for i in range(5):
            user = User.objects.create_user(
                username=f"query_test_user_{i}",
                email=f"query_test_{i}@example.com",
                password="testpass123",
            )
            author = Author.objects.create(
                user=user, first_name=f"Query{i}", last_name=f"Test{i}"
            )
            self.authors.append(author)

        # Create a hub
        self.hub = Hub.objects.create(
            name="Query Test Hub", description="Hub for testing queries"
        )

        # Get content type for hub
        self.hub_content_type = ContentType.objects.get_for_model(Hub)

        # Add editor permissions to 3 users
        for i in range(3):
            Permission.objects.create(
                user=self.authors[i].user,
                content_type=self.hub_content_type,
                object_id=self.hub.id,
                access_type=EDITOR,
            )

    def test_author_serializer_n_plus_one_queries(self):
        """Test that AuthorSerializer causes N+1 queries for permissions."""

        # First, let's serialize a single author and count queries
        print("\n=== Single Author Serialization ===")
        with CaptureQueriesContext(connection) as single_context:
            serializer = AuthorSerializer(self.authors[0])
            data = serializer.data

        print(f"Queries for 1 author: {len(single_context.captured_queries)}")

        # Count permission queries
        single_permission_queries = [
            q
            for q in single_context.captured_queries
            if "researchhub_access_group_permission" in q["sql"]
        ]
        print(f"Permission queries for 1 author: {len(single_permission_queries)}")

        # Now serialize all 5 authors
        print("\n=== Multiple Authors Serialization ===")
        with CaptureQueriesContext(connection) as multi_context:
            serializer = AuthorSerializer(self.authors, many=True)
            data = serializer.data

        print(f"Queries for 5 authors: {len(multi_context.captured_queries)}")

        # Count permission queries
        multi_permission_queries = [
            q
            for q in multi_context.captured_queries
            if "researchhub_access_group_permission" in q["sql"]
        ]
        print(f"Permission queries for 5 authors: {len(multi_permission_queries)}")

        # Print permission queries
        print("\n=== Permission Queries Detail ===")
        for i, query in enumerate(multi_permission_queries[:5]):  # Show first 5
            sql = query["sql"]
            # Extract user ID from query
            import re

            user_match = re.search(r'"user_id" = (\d+)', sql)
            user_id = user_match.group(1) if user_match else "unknown"
            print(f"Query {i+1}: Permission check for user_id={user_id}")

        # This demonstrates the N+1 problem
        print(f"\n=== N+1 Query Analysis ===")
        print(f"Expected permission queries (optimized): 1")
        print(f"Actual permission queries: {len(multi_permission_queries)}")
        print(
            f"N+1 problem detected: {'YES' if len(multi_permission_queries) > 1 else 'NO'}"
        )

        # Assert that we have the N+1 problem (for test purposes)
        self.assertGreater(
            len(multi_permission_queries), 1, "N+1 query problem should be present"
        )

    def test_researchhub_post_with_multiple_authors(self):
        """Test querying a ResearchHub post with multiple authors."""

        # Create unified document
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", is_public=True
        )
        unified_doc.hubs.add(self.hub)

        # Create post with multiple authors
        post = ResearchhubPost.objects.create(
            title="Test Post for Query Analysis",
            renderable_text="Content for testing queries.",
            created_by=self.authors[0].user,
            unified_document=unified_doc,
            document_type="DISCUSSION",
        )
        post.authors.set(self.authors)

        # Import the serializer
        from researchhub_document.serializers.researchhub_post_serializer import (
            ResearchhubPostSerializer,
        )

        print("\n=== ResearchHub Post Serialization ===")
        with CaptureQueriesContext(connection) as context:
            serializer = ResearchhubPostSerializer(post)
            data = serializer.data

        total_queries = len(context.captured_queries)
        permission_queries = [
            q
            for q in context.captured_queries
            if "researchhub_access_group_permission" in q["sql"]
        ]

        print(f"Total queries: {total_queries}")
        print(f"Permission queries: {len(permission_queries)}")
        print(f"Authors in post: {post.authors.count()}")

        # Show query breakdown
        print("\n=== Query Breakdown ===")
        query_types = {}
        for query in context.captured_queries:
            sql = query["sql"]
            if "SELECT" in sql:
                # Extract table name
                table_match = re.search(r'FROM "([^"]+)"', sql)
                if table_match:
                    table = table_match.group(1)
                    query_types[table] = query_types.get(table, 0) + 1

        for table, count in sorted(
            query_types.items(), key=lambda x: x[1], reverse=True
        ):
            print(f"{table}: {count} queries")

        # This should show multiple permission queries
        self.assertGreater(
            len(permission_queries),
            1,
            f"Expected multiple permission queries but got {len(permission_queries)}",
        )
