from django_filters import rest_framework as filters
from .models import *
from utils.filters import ListExcludeFilter

class AuthorFilter(filters.FilterSet):
    id__ne = ListExcludeFilter(field_name='id')

    class Meta:
        model = Author
        fields = [field.name for field in model._meta.fields]
        fields.append('id__ne')