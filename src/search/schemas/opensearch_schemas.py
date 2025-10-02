"""
Pydantic schemas for OpenSearch integration.
"""

from typing import List, Optional
from pydantic import BaseModel

class Triple(BaseModel):
    """Knowledge triple from OpenSearch."""
    subject: str
    predicate: str
    object: str

class Article(BaseModel):
    """Article model for OpenSearch results."""
    id: str  # Changed from int to str to handle DOI strings
    title: str
    abstract: str
    doi: Optional[str] = None
    article_doi: Optional[str] = None  # Additional field for OpenSearch DOI mapping
    date: Optional[str] = None
    authors: Optional[str] = None
    journal: Optional[str] = None
    query: Optional[str] = None
    score: Optional[float] = None
    related_triples: Optional[List[Triple]] = None  # List of related knowledge triples


class ReloadResponse(BaseModel):
    """Response model for reload operations."""
    message: str
    count: int
