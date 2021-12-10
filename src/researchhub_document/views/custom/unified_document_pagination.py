from rest_framework.pagination import PageNumberPagination


UNIFIED_DOC_PAGE_SIZE = 20


class UnifiedDocPagination(PageNumberPagination):
    page_size_query_param = 'page_limit'
    max_page_size = 200  # NOTE: arbitrary size for security
    page_size = UNIFIED_DOC_PAGE_SIZE
