from researchhub.celery import app


@app.task
def test_task(x, y):
    return x + y
