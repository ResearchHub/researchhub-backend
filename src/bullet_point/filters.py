from django_filters import rest_framework as filters
from .models import BulletPoint

class BulletPointFilter(filters.FilterSet):
    ordinal__isnull = filters.BooleanFilter(field_name='ordinal', lookup_expr='isnull')

    class Meta:
        model = BulletPoint
        fields = [field.name for field in model._meta.fields if not field.name == 'text']  # noqa: E501
        fields.append('ordinal__isnull')
        fields.append('created_by__author_profile')