from discussion.constants import (
    RELATED_DISCUSSION_MODELS,    
)
from discussion.models import Thread
from reputation.tasks import create_contribution
from reputation.models import Contribution
from discussion.serializers import ThreadSerializer

def create_thread(data, user, for_model, for_model_id, with_contribution=True):
    instance = RELATED_DISCUSSION_MODELS[for_model].objects.get(id=for_model_id)

    if for_model == 'citation':
        unified_document = instance.source
    else:
        unified_document = instance.unified_document
    
    data = _prepare_data(data, instance)
    thread = Thread.objects.create(
        **data,
        created_by=user,
    )

    if with_contribution:
        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {'app_label': 'discussion', 'model': 'thread'},
                user.id,
                unified_document.id,
                thread.id,
            ),
            priority=1,
            countdown=10
        )

    return thread

def _prepare_data(data, instance):
    if data.get('paper'):
        data['paper'] = instance
    elif data.get('post'):
        data['post'] = instance
    if data.get('hypothesis'):
        data['hypothesis'] = instance
    
    return data