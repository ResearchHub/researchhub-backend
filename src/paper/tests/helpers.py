from paper.models import Paper
from researchhub_document.related_models.constants.document_type import (
    PAPER as PAPER_DOC_TYPE,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)


class TestData:
    paper_title = (
        "Messrs Moony, Wormtail, Padfoot, and Prongs Purveyors of"
        " Aids to Magical Mischief-Makers are proud to present THE"
        " MARAUDER'S MAP"
    )
    paper_publish_date = "1990-10-01"


def create_paper(
    title=TestData.paper_title,
    paper_publish_date=TestData.paper_publish_date,
    uploaded_by=None,
    raw_authors=[],
):
    paper = Paper.objects.create(
        title=title,
        paper_publish_date=paper_publish_date,
        uploaded_by=uploaded_by,
        raw_authors=raw_authors,
    )
    unified_doc = ResearchhubUnifiedDocument.objects.create(
        document_type=PAPER_DOC_TYPE,
        score=paper.score,
    )
    paper.unified_document = unified_doc
    paper.save()

    return paper
