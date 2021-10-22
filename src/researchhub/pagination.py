from rest_framework.pagination import PageNumberPagination


class MediumPageLimitPagination(PageNumberPagination):
    page_size_query_param = 'page_limit'
    max_page_size = 100
    page_size = 100
