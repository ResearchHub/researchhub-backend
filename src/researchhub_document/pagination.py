from rest_framework.pagination import PageNumberPagination

class FeedPagination(PageNumberPagination):
    page_size = 30