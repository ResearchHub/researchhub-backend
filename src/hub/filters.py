from django_filters import rest_framework as filters
from .models import *

class HubFilter(filters.FilterSet):
    name__iexact = filters.Filter(field_name="name", lookup_expr='iexact')

    class Meta:
        model = Hub
        fields = [field.name for field in model._meta.fields if not field.name == 'file']