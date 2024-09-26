import json
from datetime import datetime

from paper.related_models.async_paper_updator_model import AsyncPaperUpdator
from paper.related_models.citation_model import Citation
from paper.related_models.paper_model import (
    ARXIV_IDENTIFIER,
    DOI_IDENTIFIER,
    HELP_TEXT_IS_PUBLIC,
    HELP_TEXT_IS_REMOVED,
    HOT_SCORE_WEIGHT,
    AdditionalFile,
    Figure,
    Paper,
    PaperFetchLog,
)
from paper.related_models.paper_submission_model import PaperSubmission
