from django.db import models
from django_filters import rest_framework as filters
from .models import Author
from utils.filters import ListExcludeFilter
from user.models import User


class AuthorFilter(filters.FilterSet):
    id__ne = ListExcludeFilter(field_name='id')
    education = filters.CharFilter(lookup_expr='icontains')
    headline = filters.CharFilter(lookup_expr='icontains')

    class Meta:
        model = Author
        fields = [field.name for field in model._meta.fields]
        fields.append('id__ne')
        filter_overrides = {
            models.FileField: {
                'filter_class': filters.CharFilter,
            }
        }

class UserFilter(filters.FilterSet):
    invited_by = filters.NumberFilter()
    referral_code = filters.Filter()

    class Meta:
        model = User
        fields = []
