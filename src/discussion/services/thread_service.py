from discussion.constants import (
    RELATED_DISCUSSION_MODELS,    
)
from reputation.tasks import create_contribution
from reputation.models import Contribution
from discussion.serializers import ThreadSerializer
from review.serializers.review_serializer import ReviewSerializer


def create_thread(data, user, for_model, for_model_id, context, with_contribution=True):
    instance = RELATED_DISCUSSION_MODELS[for_model].objects.get(id=for_model_id)

    if for_model == 'citation':
        unified_document = instance.source
    else:
        unified_document = instance.unified_document
    
    serializer = ThreadSerializer(data=data, context=context)
    serializer.is_valid()
    thread = serializer.create(serializer.validated_data)

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
