from django.db import models

# Create your models here.


class Profile(models.Model):
    view_name = models.CharField(max_length=64)
    path = models.CharField(max_length=256)
    http_method = models.CharField(max_length=8)
    total_queries = models.CharField(max_length=8)
    total_sql_time = models.CharField(max_length=64)
    total_view_time = models.CharField(max_length=64)

    created_date = models.DateTimeField(auto_now_add=True)


class Traceback(models.Model):
    SQL_TRACE = 'SQL_TRACE'
    VIEW_TRACE = 'VIEW_TRACE'
    TRACE_TYPE_CHOICES = [
        (SQL_TRACE, 'SQL_TRACE'),
        (VIEW_TRACE, 'VIEW_TRACE')
    ]
    choice_type = models.CharField(choices=TRACE_TYPE_CHOICES, max_length=16)
    time = models.CharField(max_length=64)

    trace = models.TextField()
    sql = models.TextField(null=True, blank=True)

    profile = models.ForeignKey(
        Profile,
        related_name='traceback',
        on_delete=models.CASCADE
    )
