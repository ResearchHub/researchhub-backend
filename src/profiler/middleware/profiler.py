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

from io import StringIO
from django.db import connection
from profiler.tasks import log_traceback
from utils import sentry

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
        if hasattr(callback, 'cls'):
            view_name = str(callback.cls)
        else:
            view_name = str(callback)

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

    def process_response(self, request, response):
        if 'api' in request.path:
            try:
                self.prof.disable()

                out = StringIO()
                old_stdout = sys.stdout
                sys.stdout = out
                stats = pstats.Stats(self.prof, stream=out)

                stats.print_stats()

                sys.stdout = old_stdout
                stats_str = out.getvalue()
                total_time = str(stats.total_tt)
            except Exception as e:
                sentry.log_error(e)
                return response

            log_traceback.apply_async(
                (self.data, total_time, stats_str),
                priority=1,
            )

        return response
