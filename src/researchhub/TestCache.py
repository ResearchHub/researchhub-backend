from django.core.cache.backends.locmem import LocMemCache


class TestCache(LocMemCache):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def delete_pattern(self, *args, **kwargs):
        return

    def get_or_set(self, *args, **kwargs):
        return
