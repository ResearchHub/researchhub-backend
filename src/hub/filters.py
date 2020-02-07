from django_filters import rest_framework as filters
from .models import Hub

class ScoreOrderingFilter(filters.OrderingFilter):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extra['choices'] += ['score', '-score']

    def filter(self, qs, value):
        if value and any(v in ['score', '-score'] for v in value):
            return qs.order_by(*value)
        else:
            return super().filter(qs, value)

class HubFilter(filters.FilterSet):
    name__iexact = filters.Filter(field_name="name", lookup_expr='iexact')
    ordering = ScoreOrderingFilter(fields=['name', 'score'])

    class Meta:
        model = Hub
        fields = [field.name for field in model._meta.fields if not field.name == 'file']  # noqa: E501
        #fields.append('score')
