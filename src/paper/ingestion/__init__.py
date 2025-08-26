"""
Paper Ingestion Pipeline

A 3-stage pipeline for ingesting papers from multiple sources:
1. Fetch & Store Raw: Fetch from APIs and store raw responses
2. Process: Parse raw responses and extract paper metadata
3. Deduplicate & Enrich: Cross-source deduplication and storage
"""

__version__ = "1.0.0"
