from django.db.models import FileField
from django_filters import rest_framework as filters

from .models import Hub

class HubFilter(filters.FilterSet):
    name__iexact = filters.CharFilter(field_name="name", lookup_expr="iexact")

    class Meta:
        model = Hub
        fields = [field.name for field in model._meta.fields]
        filter_overrides = {
            FileField: {
                "filter_class": filters.CharFilter,
            }
        }
