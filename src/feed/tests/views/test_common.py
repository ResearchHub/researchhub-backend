from unittest.mock import Mock

from django.test import TestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from feed.views.common import FeedPagination


class FeedPaginationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.pagination = FeedPagination()

    def test_pagination_no_next_link_when_results_less_than_page_size(self):
        """
        Test that no next link is included when results are less than page size.
        This prevents repeated requests for empty pages.
        """
        # Set up pagination with DRF Request
        django_request = self.factory.get("/api/feed/?page=1&page_size=20")
        request = Request(django_request)
        self.pagination.request = request
        self.pagination.page = Mock()
        self.pagination.page.has_next = Mock(return_value=True)

        # Create mock data with fewer items than page size
        data = [{"id": i} for i in range(5)]  # 5 items, page_size is 20

        response = self.pagination.get_paginated_response(data)

        # Should not have next link when results < page_size
        self.assertIsNone(response.data["next"])

    def test_pagination_includes_next_link_when_results_equal_page_size(self):
        """
        Test that next link is included when results equal page size.
        This indicates there may be more pages available.
        """
        # Set up pagination with DRF Request
        django_request = self.factory.get("/api/feed/?page=1&page_size=20")
        request = Request(django_request)
        self.pagination.request = request
        self.pagination.page = Mock()
        self.pagination.page.has_next = Mock(return_value=True)

        # Create mock data with exactly page_size items
        data = [{"id": i} for i in range(20)]  # 20 items, page_size is 20

        response = self.pagination.get_paginated_response(data)

        # Should have next link when results == page_size
        self.assertIsNotNone(response.data["next"])

    def test_pagination_includes_next_link_when_results_greater_than_page_size(self):
        """
        Test that next link is included when results exceed page size.
        This should not happen in practice, but tests edge case.
        """
        # Set up pagination with DRF Request
        django_request = self.factory.get("/api/feed/?page=1&page_size=20")
        request = Request(django_request)
        self.pagination.request = request
        self.pagination.page = Mock()
        self.pagination.page.has_next = Mock(return_value=True)

        # Create mock data with more items than page size
        data = [{"id": i} for i in range(25)]  # 25 items, page_size is 20

        response = self.pagination.get_paginated_response(data)

        # Should have next link when results > page_size
        self.assertIsNotNone(response.data["next"])

    def test_pagination_respects_custom_page_size(self):
        """
        Test that pagination respects custom page_size query parameter.
        """
        # Set up pagination with custom page_size
        django_request = self.factory.get("/api/feed/?page=1&page_size=10")
        request = Request(django_request)
        self.pagination.request = request
        self.pagination.page = Mock()
        self.pagination.page.has_next = Mock(return_value=True)

        # Create mock data with exactly custom page_size items
        data = [{"id": i} for i in range(10)]  # 10 items, custom page_size is 10

        response = self.pagination.get_paginated_response(data)

        # Should have next link when results == custom page_size
        self.assertIsNotNone(response.data["next"])

        # Create mock data with fewer than custom page_size items
        data = [{"id": i} for i in range(5)]  # 5 items, custom page_size is 10

        response = self.pagination.get_paginated_response(data)

        # Should not have next link when results < custom page_size
        self.assertIsNone(response.data["next"])
