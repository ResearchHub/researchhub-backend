from django.db.models import Aggregate, FloatField

class TenPercentile(Aggregate):
    function = 'PERCENTILE_CONT'
    name = 'ten-percentile'
    output_field = FloatField()
    template = '%(function)s(0.99) WITHIN GROUP (ORDER BY %(expressions)s)'
