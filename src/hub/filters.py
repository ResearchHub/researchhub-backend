from django_filters import rest_framework as filters
from .models import *

class HubFilter(filters.FilterSet):
    hubs_id__in = filters.Filter(field_name="hubs", lookup_expr='in')

    class Meta:
        model = Hub
        fields = [field.name for field in model._meta.fields if not field.name == 'file']