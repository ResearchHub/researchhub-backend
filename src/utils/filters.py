from django.db.models import Q
from django_filters import rest_framework as filters

FIELD_LOOKUPS = (
    'exact',
    'iexact',
    'contains',
    'icontains',
    'in',
    'gt',
    'gte',
    'lt',
    'lte',
    'startswith',
    'istartswith',
    'endswith',
    'iendswith',
    'range',
    'date',
    'year',
    'iso_year',
    'month',
    'day',
    'week',
    'week_day',
    'quarter',
    'time',
    'hour',
    'minute',
    'second',
    'isnull',
    'regex',
    'iregex'
)


class ListFilter(filters.CharFilter):

    def __init__(self, **kwargs):
        super(ListFilter, self).__init__(**kwargs)

    def sanitize(self, value_list):
        """
        remove empty items in case of ?number=1,,2
        """
        return [v for v in value_list if v != u'']

    def customize(self, value):
        return value

    def filter(self, qs, value):
        multiple_vals = value.split(u",")
        multiple_vals = self.sanitize(multiple_vals)
        multiple_vals = map(self.customize, multiple_vals)
        f = Q()
        for v in multiple_vals:
            kwargs = {self.field_name: v}
            f = f | Q(**kwargs)
        return qs.filter(f).distinct()


class ListExcludeFilter(filters.CharFilter):

    def __init__(self, **kwargs):
        super(ListExcludeFilter, self).__init__(**kwargs)

    def sanitize(self, value_list):
        """
        remove empty items in case of ?number=1,,2
        """
        return [v for v in value_list if v != u'']

    def customize(self, value):
        return value

    def filter(self, qs, value):
        multiple_vals = value.split(u",")
        multiple_vals = self.sanitize(multiple_vals)
        multiple_vals = map(self.customize, multiple_vals)
        f = Q()
        for v in multiple_vals:
            kwargs = {self.field_name: v}
            f = f | Q(**kwargs)
        return qs.exclude(f)


class OrFilter(filters.CharFilter):
    '''
    Syntax:

    ?or_filter=field1|field2|field3~value1,value2

    '''
    def __init__(self, **kwargs):
        self.model = kwargs.pop('model', None)

        if self.model is None or not hasattr(self.model, '_meta'):
            raise ValueError('no model provided to or_filter')

        # Force field_name to be or_filter?
        # if kwargs.get('field_name', 'or_filter') != 'or_filter':
        #    raise ValueError('OrFilter must have field_name as "or_filter"')
        # kwargs['field_name'] = 'or_filter'

        # Set field_name to or_filter if none provided
        if kwargs.get('field_name') is None:
            kwargs['field_name'] = 'or_filter'

        super(OrFilter, self).__init__(**kwargs)

    def sanitize_keys(self, keys):
        """
        """
        return [k for k in keys if self.is_valid_field(k)]

    def is_valid_field(self, key):
        return key != u'' and self.get_field(key, self.model)

    def get_field(self, field, model):
        if '__' in field:
            if field[field.index('__') + 2:] in FIELD_LOOKUPS:
                return self.get_field(field[:field.index('__')], model)
            return self.get_field(
                field[field.index('__') + 2:],
                model._meta.get_field(field[:field.index('__')]).related_model
            )
        else:
            return model._meta.get_field(field)

    def sanitize_values(self, value_list):
        """
        remove empty items in case of ~1,,2
        """
        return [v for v in value_list if v != u'']

    def sanitize_value(self, key, value):
        """
        """
        if not value:
            raise ValueError('no value provided')

        internal_type = self.get_field(key, self.model).get_internal_type()
        if internal_type == 'BooleanField':
            return value.lower() == 'true'
        elif internal_type == 'AutoField' or internal_type == 'IntegerField':
            return int(value)
        else:
            return value

    def filter(self, qs, value):
        if value == u'':
            return qs

        key_names, values = value.split(u'~')
        keys = key_names.split(u'|')

        sanitized_keys = self.sanitize_keys(keys)
        sanitized_values = self.sanitize_values(values.split(u','))

        f = Q()
        for k in sanitized_keys:
            for v in sanitized_values:
                val = self.sanitize_value(k, v)
                or_expr = {k: val}
                f = f | Q(**or_expr)

        return qs.filter(f)
