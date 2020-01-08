from __future__ import absolute_import, unicode_literals
from researchhub.celery import app


@app.task
def test(x, y):
    return x + y
