from researchhub_document.models import (
    ResearchhubPost, ResearchhubUnifiedDocument
)
from hypothesis.related_models.hypothesis import Hypothesis


def create_post(
    title='Some random post title',
    renderable_text='some text',
    created_by=None,
    document_type='DISCUSSION'
):

    uni_doc = ResearchhubUnifiedDocument.objects.create(
      document_type=document_type,
    )

    return ResearchhubPost.objects.create(
        title=title,
        created_by=created_by,
        document_type=document_type,
        renderable_text=renderable_text,
        unified_document=uni_doc
    )

def create_hypothesis(
    title='Some random hypothesis title',
    renderable_text='some text',
    created_by=None
):

    uni_doc = ResearchhubUnifiedDocument.objects.create(
      document_type='HYPOTHESIS',
    )

    return Hypothesis.objects.create(
        title=title,
        created_by=created_by,
        renderable_text=renderable_text,
        unified_document=uni_doc
    )