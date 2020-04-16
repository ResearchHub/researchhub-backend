# Orignal version taken from http://www.djangosnippets.org/snippets/186/
# Original author: udfalkso
# Modified by: Shwagroo Team and Gun.io

import sys
import re
import json
import cProfile
import pstats
import time
import traceback
import sqlparse

from io import StringIO
from django.db import connection
from profiler.models import Profile, Traceback
from utils import sentry

words_re = re.compile(r'\s+')

group_prefix_re = [
    re.compile(r'^.*/django/[^/]+'),
    re.compile(r'^(.*)/[^/]+$'),  # extract module path
    re.compile(r'.*'),            # catch strange entries
]
sql_expain_re = re.compile(
    r'\(cost=(?P<cost>[^ ]+) rows=(?P<rows>\d+) width=(?P<width>\d+)\)'
)


class TracebackLogger:
    def __init__(self):
        self.tracebacks = []

    def capture_traceback(self):
        tb = ''.join(traceback.format_stack())
        self.tracebacks.append(tb)

    def __call__(self, execute, sql, params, many, context):
        start = time.monotonic()
        self.start = start

        try:
            result = execute(sql, params, many, context)
        except Exception as e:
            sentry.log_error(e)
            raise

        self.capture_traceback()
        return result


class ProfileMiddleware(object):
    """
    Displays cProfile profiling for any view.
    http://yoursite.com/yourview/?prof

    Add the "prof" key to query string by appending ?prof (or &prof=)
    and you'll see the profiling results in your browser.
    """
    def __init__(self, get_response):
        self.prof = cProfile.Profile()
        self.get_response = get_response

    def __call__(self, request):
        response = self.process_request(request)

        response = self.get_response(request)

        response = self.process_response(request, response)

        return response

    def get_sql_explaination(self, sql):
        with connection.cursor() as cursor:
            cursor.execute(f'EXPLAIN {sql}')
            return '\n'.join(r[0] for r in cursor.fetchall())

    def create_traceback(self, request, callback, tracebacks, queries):
        view_name = str(callback.cls)
        path = request.build_absolute_uri()
        http_method = request.method

        for tb, q in zip(tracebacks, queries):
            q['traceback'] = tb
            explain = self.get_sql_explaination(q['sql'])

            result = sql_expain_re.search(explain.split('\n')[0])
            q['explain'] = explain
            q['explain_cost'] = result.group("cost")
            q['explain_rows'] = result.group("rows")
            q['explain_width'] = result.group("width")

        total_duration = sum(float(q['time']) for q in queries) * 1000
        request_data = {
            'view_name': view_name,
            'path': path,
            'http_method': http_method,
            'total_time': total_duration,
            'total_queries': len(queries),
            'paths': json.dumps(sys.path[1:]),
            'queries': queries,
        }
        self.data = request_data

    def log_traceback(self, total_view_time, traceback):
        queries = self.data['queries']
        view_name = self.data['view_name']
        path = self.data['path']
        http_method = self.data['http_method']
        total_queries = str(self.data['total_queries'])
        total_sql_time = str(self.data['total_time'])
        total_view_time = str(total_view_time)

        try:
            profile = Profile.objects.create(
                view_name=view_name,
                path=path,
                http_method=http_method,
                total_queries=total_queries,
                total_sql_time=total_sql_time,
                total_view_time=total_view_time
            )
            Traceback.objects.create(
                profile=profile,
                choice_type=Traceback.VIEW_TRACE,
                time=total_view_time,
                trace=traceback
            )
            for query in queries:
                choice_type = Traceback.SQL_TRACE
                sql = query.get('sql')
                trace = query.get('traceback', '')
                time = query.get('time')
                Traceback.objects.create(
                    profile=profile,
                    choice_type=choice_type,
                    time=time,
                    trace=trace,
                    sql=sql
                )
        except Exception as e:
            sentry.log_error(e)

    def process_request(self, request):
        if 'api' in request.path:
            self.prof = cProfile.Profile()

    def process_view(self, request, callback, callback_args, callback_kwargs):
        if 'api' in request.path:
            logger = TracebackLogger()
            self.prof.enable()

            with connection.execute_wrapper(logger):
                response = self.prof.runcall(
                    callback,
                    request,
                    *callback_args,
                    **callback_kwargs
                )

            self.prof.disable()
            queries = connection.queries.copy()
            self.create_traceback(
                request,
                callback,
                logger.tracebacks,
                queries
            )
            return response

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

    def process_response(self, request, response):
        if 'api' in request.path:
            self.prof.disable()

            out = StringIO()
            old_stdout = sys.stdout
            sys.stdout = out

            stats = pstats.Stats(self.prof, stream=out)
            stats.sort_stats('time', 'calls')
            stats.print_stats()

            sys.stdout = old_stdout
            stats_str = out.getvalue()
            total_time = str(stats.total_tt)

            self.log_traceback(total_time, stats_str)

        return response
