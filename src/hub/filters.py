from django.db.models import FileField
from django_filters import rest_framework as filters

from .models import Hub

class HubFilter(filters.FilterSet):
    name__iexact = filters.CharFilter(field_name="name", lookup_expr="iexact")

    class Meta:
        model = Hub
        fields = "__all__"
        filter_overrides = {
            FileField: {
                "filter_class": filters.CharFilter,
            }
        }
