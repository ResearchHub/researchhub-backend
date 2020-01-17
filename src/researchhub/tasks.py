from __future__ import absolute_import, unicode_literals
from researchhub.celery import app


@app.task
def test_task(x, y):
    return x + y
