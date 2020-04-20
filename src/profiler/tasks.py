import os

from datetime import datetime
from django.core.files import File
from researchhub.celery import app
from profiler.models import Profile, Traceback
from utils import sentry


@app.task
def log_traceback(data, total_view_time, traceback):
    queries = data['queries']
    view_name = data['view_name']
    path = data['path']
    http_method = data['http_method']
    total_queries = str(data['total_queries'])
    total_sql_time = data['total_time']
    total_view_time = total_view_time

    try:
        profile = Profile.objects.create(
            view_name=view_name,
            path=path,
            http_method=http_method,
            total_queries=total_queries,
            total_sql_time=total_sql_time,
            total_view_time=total_view_time
        )

        filename = f'/tmp/trace_logs/{str(datetime.now())}.log'
        with open(filename, 'wb+') as f:
            f.write(traceback.encode())
            Traceback.objects.create(
                profile=profile,
                choice_type=Traceback.VIEW_TRACE,
                time=total_view_time,
                trace=File(f)
            )
        os.remove(filename)
        for i, query in enumerate(queries):
            choice_type = Traceback.SQL_TRACE
            sql = query.get('sql')
            trace = query.get('traceback', '')
            time = query.get('time')
            filename = f'/tmp/trace_logs/{str(datetime.now())}.log'
            with open(filename, 'wb+') as f:
                f.write(trace.encode())
                Traceback.objects.create(
                    profile=profile,
                    choice_type=choice_type,
                    time=time,
                    trace=File(f),
                    sql=sql
                )
            os.remove(filename)
    except Exception as e:
        sentry.log_error(e)
