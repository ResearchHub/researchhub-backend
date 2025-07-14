"""
Minimal demonstration of the N+1 query issue with permissions.
This test creates fresh data to avoid conflicts.
"""

import uuid

from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from hub.models import Hub
from researchhub_access_group.constants import EDITOR
from researchhub_access_group.models import Permission
from user.models import Author, User
from user.serializers import AuthorSerializer


class PermissionQueryDemoTest(TestCase):
    """Demonstrate the N+1 query issue in AuthorSerializer."""

    @classmethod
    def setUpTestData(cls):
        """Create test data once for all tests."""
        # Use unique identifiers to avoid conflicts
        unique_id = str(uuid.uuid4())[:8]

        # Create test users with unique usernames
        cls.test_users = []
        cls.test_authors = []

        for i in range(3):
            user = User.objects.create_user(
                username=f"perm_test_{unique_id}_{i}",
                email=f"perm_test_{unique_id}_{i}@test.com",
                password="testpass",
            )
            author = Author.objects.create(
                user=user, first_name=f"PermTest{i}", last_name=f"{unique_id}"
            )
            cls.test_users.append(user)
            cls.test_authors.append(author)

        # Create a test hub
        cls.test_hub = Hub.objects.create(
            name=f"Permission Test Hub {unique_id}",
            description="Hub for permission query testing",
        )

        # Get hub content type
        cls.hub_content_type = ContentType.objects.get_for_model(Hub)

        # Give editor permissions to first 2 users
        for i in range(2):
            Permission.objects.create(
                user=cls.test_users[i],
                content_type=cls.hub_content_type,
                object_id=cls.test_hub.id,
                access_type=EDITOR,
            )

    def test_demonstrates_n_plus_one_queries(self):
        """Show that serializing multiple authors causes N+1 permission queries."""

        print("\n" + "=" * 60)
        print("N+1 QUERY DEMONSTRATION")
        print("=" * 60)

        # Test 1: Serialize single author
        print("\n1. Serializing ONE author:")
        with CaptureQueriesContext(connection) as ctx:
            serializer = AuthorSerializer(self.test_authors[0])
            _ = serializer.data

        permission_queries = [
            q
            for q in ctx.captured_queries
            if "researchhub_access_group_permission" in q["sql"]
        ]

        print(f"   - Total queries: {len(ctx.captured_queries)}")
        print(f"   - Permission queries: {len(permission_queries)}")

        # Test 2: Serialize multiple authors
        print("\n2. Serializing THREE authors:")
        with CaptureQueriesContext(connection) as ctx:
            serializer = AuthorSerializer(self.test_authors, many=True)
            _ = serializer.data

        permission_queries = [
            q
            for q in ctx.captured_queries
            if "researchhub_access_group_permission" in q["sql"]
        ]

        print(f"   - Total queries: {len(ctx.captured_queries)}")
        print(f"   - Permission queries: {len(permission_queries)}")

        # Analysis
        print("\n3. Analysis:")
        print(f"   - We serialized {len(self.test_authors)} authors")
        print(
            f"   - Each author triggers permission queries in get_added_as_editor_date()"
        )
        print(f"   - Result: {len(permission_queries)} separate permission queries")
        print(f"   - This is the N+1 query problem!")

        # Show the actual queries
        print("\n4. Permission queries executed:")
        for i, query in enumerate(permission_queries, 1):
            sql = query["sql"]
            # Extract user_id from the query
            if "user_id" in sql:
                import re

                match = re.search(r'"user_id" = (\d+)', sql)
                if match:
                    user_id = match.group(1)
                    print(f"   Query {i}: Check permissions for user_id={user_id}")

        print("\n" + "=" * 60)

        # The test passes if we have N+1 queries (demonstrating the issue exists)
        self.assertEqual(
            len(permission_queries),
            len(self.test_authors),
            f"Expected {len(self.test_authors)} permission queries (N+1 problem), "
            f"but got {len(permission_queries)}",
        )
