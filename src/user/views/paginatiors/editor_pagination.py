from django.core.paginator import Paginator


EDITOR_PAGE_SIZE = 20


class EditorPagination(Paginator):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
