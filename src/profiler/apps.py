import os

from django.apps import AppConfig


class ProfilerConfig(AppConfig):
    name = 'profiler'

    def ready(self):
        if not os.path.isdir('/tmp/trace_logs'):
            os.mkdir('/tmp/trace_logs')
