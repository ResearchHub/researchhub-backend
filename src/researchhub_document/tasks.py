from django.contrib.contenttypes.models import ContentType
from django_opensearch_dsl.registries import registry

from researchhub.celery import QUEUE_ELASTIC_SEARCH, QUEUE_HOT_SCORE, app
from utils import sentry


@app.task(queue=QUEUE_HOT_SCORE)
def recalc_hot_score_task(instance_content_type_id, instance_id):
    content_type = ContentType.objects.get(id=instance_content_type_id)
    model_name = content_type.model
    model_class = content_type.model_class()
    uni_doc = None

    try:
        if model_name in [
            "bounty",
            "contribution",
            "paper",
            "researchhubpost",
        ]:
            uni_doc = model_class.objects.get(id=instance_id).unified_document
        elif model_name == "citation":
            uni_doc = model_class.objects.get(id=instance_id).source

        if uni_doc:
            # Recalculate and save hot score on the unified document
            hot_score, _ = uni_doc.calculate_hot_score(should_save=True)

    except Exception as error:
        sentry.log_error(error)


@app.task(queue=QUEUE_ELASTIC_SEARCH)
def update_elastic_registry(post):
    registry.update(post)
