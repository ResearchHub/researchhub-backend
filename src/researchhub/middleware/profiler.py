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
from datetime import datetime
from django.db import connection
from django.conf import settings

words_re = re.compile(r'\s+')

group_prefix_re = [
    re.compile("^.*/django/[^/]+"),
    re.compile("^(.*)/[^/]+$"),  # extract module path
    re.compile(".*"),            # catch strange entries
]
sql_expain_re = re.compile(
    r"\(cost=(?P<cost>[^ ]+) rows=(?P<rows>\d+) width=(?P<width>\d+)\)"
)


class TracebackLogger:
    def __init__(self):
        self.tracebacks = []

    def capture_traceback(self):
        tb = ''.join(traceback.format_stack())
        self.tracebacks.append(tb)

    def __call__(self, execute, sql, params, many, context):
        start = time.monotonic()

        try:
            result = execute(sql, params, many, context)
        except Exception as e:
            raise

        self.capture_traceback()
        return result


class ProfileMiddleware(object):
    """
    Displays cProfile profiling for any view.
    http://yoursite.com/yourview/?prof

    Add the "prof" key to query string by appending ?prof (or &prof=)
    and you'll see the profiling results in your browser.
    It's set up to only be available in django's debug mode, is available for superuser otherwise,
    but you really shouldn't add this middleware to any production configuration.
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

    def process_request(self, request):
        if (settings.DEBUG or request.user.is_superuser) and 'prof' in request.GET:
            self.prof = cProfile.Profile()

    def process_view(self, request, callback, callback_args, callback_kwargs):
        if (settings.DEBUG or request.user.is_superuser) and 'prof' in request.GET:
            if 'sql' in request.GET:
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
                for tb, q in zip(logger.tracebacks, queries):
                    q['traceback'] = tb
                    explain = self.get_sql_explaination(q['sql'])

                    result = sql_expain_re.search(explain.split('\n')[0])
                    q['explain'] = explain
                    q['explain_cost'] = result.group("cost")
                    q['explain_rows'] = result.group("rows")
                    q['explain_width'] = result.group("width")

                total_duration = sum(float(q['time']) for q in queries)
                request_data = {
                    'method': request.method,
                    'created_at': datetime.now().isoformat(),
                    'endpoint': request.build_absolute_uri(),
                    'total_time': total_duration,
                    'total_queries': len(queries),
                    'paths': json.dumps(sys.path[1:]),
                    'queries': queries,
                }
                self.data = request_data
            else:
                self.prof.enable()
                response = self.prof.runcall(
                    callback,
                    request,
                    *callback_args,
                    **callback_kwargs
                )
            return response

    def get_group(self, file):
        for g in group_prefix_re:
            name = g.findall(file)
            if name:
                return name[0]

    def get_summary(self, results_dict, sum):
        list = [(item[1], item[0]) for item in results_dict.items()]
        list.sort(reverse=True)
        list = list[:40]

        res = "      tottime\n"
        for item in list:
            res += "%4.1f%% %7.3f %s\n" % (100*item[0]/sum if sum else 0, item[0], item[1])

        return res

    def summary_for_files(self, stats_str):
        stats_str = stats_str.split("\n")[5:]

        mystats = {}
        mygroups = {}

        sum = 0

        for s in stats_str:
            fields = words_re.split(s)
            if len(fields) == 7:
                time = float(fields[2])
                sum += time
                file = fields[6].split(":")[0]

                if file not in mystats:
                    mystats[file] = 0
                mystats[file] += time

                group = self.get_group(file)
                if group not in mygroups:
                    mygroups[group] = 0
                mygroups[group] += time

        return "<pre>" + \
               " ---- By file ----\n\n" + self.get_summary(mystats, sum) + "\n" + \
               " ---- By group ---\n\n" + self.get_summary(mygroups, sum) + \
               "</pre>"

    def process_response(self, request, response):
        if (settings.DEBUG or request.user.is_superuser) and 'prof' in request.GET:
            self.prof.disable()

            out = StringIO()
            old_stdout = sys.stdout
            sys.stdout = out

            stats = pstats.Stats(self.prof, stream=out)
            stats.sort_stats('time', 'calls')
            stats.print_stats()

            sys.stdout = old_stdout
            stats_str = out.getvalue()

            if response and response.content and stats_str:
                response.content = "<pre>" + stats_str + "</pre>"

            response.content = "\n".join(response.content.decode('utf8').split("\n")[:40])
            response.content += self.summary_for_files(stats_str).encode()

            method = self.data['method']
            endpoint = self.data['endpoint']
            tottime = self.data['total_time']
            totqueries = self.data['total_queries']
            response.content += f'Method: {method}\n'.encode()
            response.content += f'Endpoint: {endpoint}\n'.encode()
            response.content += f'Total Time: {tottime}\n'.encode()
            response.content += f'Queries: {totqueries}\n\n'.encode()

            total_sql_time = 0
            for query in self.data['queries']:
                query_time = float(query['time'])
                total_sql_time += query_time
                sql = sqlparse.format(
                    query['sql'],
                    reindent=True,
                    keyword_case='upper'
                )
                response.content += f'Time: {query_time}\n'.encode()
                response.content += f'SQL:\n{sql}\n\n'.encode()
            total_sql_time *= 1000
            response.content += f'SQL Time: {total_sql_time} ms\n\n'.encode()

        return response
