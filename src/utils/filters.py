from django.db.models import Q
from django_filters import rest_framework as filters


class ListExcludeFilter(filters.CharFilter):
    def __init__(self, **kwargs):
        super(ListExcludeFilter, self).__init__(**kwargs)

    def sanitize(self, value_list):
        """
        remove empty items in case of ?number=1,,2
        """
        return [v for v in value_list if v != ""]

    def customize(self, value):
        return value

    def filter(self, qs, value):
        multiple_vals = value.split(",")
        multiple_vals = self.sanitize(multiple_vals)
        multiple_vals = map(self.customize, multiple_vals)
        f = Q()
        for v in multiple_vals:
            kwargs = {self.field_name: v}
            f = f | Q(**kwargs)
        return qs.exclude(f)
