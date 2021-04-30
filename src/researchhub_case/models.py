from .related_models.researchhub_case_abstract_model import (
  AbstractResearchhubCase
)
from .related_models.author_claim_case_model import AuthorClaimCase

migratables = (
  AbstractResearchhubCase,
  AuthorClaimCase
)