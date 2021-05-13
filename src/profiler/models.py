import re
import requests
import sqlparse

from django.db import models

# Create your models here.

words_re = re.compile(r'\s+')

group_prefix_re = [
    re.compile(r'^.*/django/[^/]+'),
    re.compile(r'^(.*)/[^/]+$'),  # extract module path
    re.compile(r'.*'),            # catch strange entries
]


class Profile(models.Model):
    view_name = models.CharField(max_length=64)
    path = models.CharField(max_length=256)
    http_method = models.CharField(max_length=8)
    total_queries = models.CharField(max_length=8)
    total_sql_time = models.FloatField()
    total_view_time = models.FloatField()

    created_date = models.DateTimeField(auto_now_add=True)


class Traceback(models.Model):
    SQL_TRACE = 'SQL_TRACE'
    VIEW_TRACE = 'VIEW_TRACE'
    TRACE_TYPE_CHOICES = [
        (SQL_TRACE, 'SQL_TRACE'),
        (VIEW_TRACE, 'VIEW_TRACE')
    ]
    choice_type = models.CharField(choices=TRACE_TYPE_CHOICES, max_length=16)
    time = models.FloatField()

    trace = models.FileField(
        max_length=512,
        upload_to='uploads/traceback/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )
    sql = models.TextField(null=True, blank=True)

    profile = models.ForeignKey(
        Profile,
        related_name='traceback',
        on_delete=models.CASCADE
    )

    def get_group(self, file):
        for g in group_prefix_re:
            name = g.findall(file)
            if name:
                return name[0]

    def get_summary(self, results_dict, _sum):
        list = [(item[1], item[0]) for item in results_dict.items()]
        list.sort(reverse=True)
        list = list[:40]

        res = '      tottime\n'
        for item in list:
            res += '%4.1f%% %7.3f %s\n' % (
                100*item[0]/_sum if _sum else 0, item[0], item[1]
            )

        return res

    def summary_for_files(self, stats_str):
        stats_str = stats_str.split("\n")[5:]

        mystats = {}
        mygroups = {}

        _sum = 0

        for s in stats_str:
            fields = words_re.split(s)
            if len(fields) == 7:
                time = float(fields[2])
                _sum += time
                file = fields[6].split(":")[0]

                if file not in mystats:
                    mystats[file] = 0
                mystats[file] += time

                group = self.get_group(file)
                if group not in mygroups:
                    mygroups[group] = 0
                mygroups[group] += time

        return '<pre>' + \
               ' ---- By file ----\n\n' + self.get_summary(mystats, _sum) + \
               '\n' + \
               ' ---- By group ---\n\n' + self.get_summary(mygroups, _sum) + \
               '</pre>'

    def get_formatted_trace(self):
        if self.choice_type == self.VIEW_TRACE:
            res = requests.get(self.trace.url)
            return self.summary_for_files(res.content.decode('utf8'))

    def get_formatted_sql(self):
        if not self.sql:
            return

        formatted_sql = sqlparse.format(
            self.sql,
            reindent=True,
            keyword_case='upper'
        )
        return formatted_sql
