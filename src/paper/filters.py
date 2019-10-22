from django_filters import rest_framework as filters
from .models import *

class PaperFilter(filters.FilterSet):

    class Meta:
        model = Paper
        fields = [field.name for field in model._meta.fields if not field.name == 'file']