import json
import logging
import os
from typing import List, Optional

import boto3
from django.conf import settings
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

from search.schemas.opensearch_schemas import Article

logger = logging.getLogger(__name__)


class OpenSearchService:
    """Service for interacting with OpenSearch for research articles."""

    def __init__(self):
        """Initialize the OpenSearch service."""
        self._client = None
        self._bedrock_client = None
        self._initialize_clients()

    def _initialize_clients(self):
        """Initialize OpenSearch and Bedrock clients if configured."""

        if not settings.OPENSEARCH_AWS_HOST:
            return

        try:
            # --- CRITICAL FIX FOR IAM USER KEYS ---
            # If AWS_SESSION_TOKEN exists in the environment, it will cause
            # 'UnrecognizedClientException' when using IAM user keys with boto3.
            # Explicitly remove it before boto3 initializes its session.
            if "AWS_SESSION_TOKEN" in os.environ:
                del os.environ["AWS_SESSION_TOKEN"]

            # Also ensure AWS_PROFILE isn't set, as it can confuse boto3's
            # credential lookup
            if "AWS_PROFILE" in os.environ:
                del os.environ["AWS_PROFILE"]

            # Boto3 will now correctly resolve credentials from environment variables
            # (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) without a session token.
            aws_region = os.environ.get("AWS_REGION", settings.OPENSEARCH_AWS_REGION)
            session = boto3.Session(region_name=aws_region)

            credentials = session.get_credentials().get_frozen_credentials()
            if (
                not credentials
                or not credentials.access_key
                or not credentials.secret_key
            ):
                raise RuntimeError(
                    """❌ No valid AWS credentials (Access Key/Secret Key)
                    resolved from environment for OpenSearch/Bedrock."""
                )

            # AWS4Auth for OpenSearch.
            # Since credentials.token should now be None, it will be correctly omitted.
            awsauth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                settings.OPENSEARCH_AWS_REGION,  # Use settings for region
                "aoss",  # Correct for OpenSearch Serverless
                session_token=credentials.token,  # This will be None, correctly omitted
            )

            # OpenSearch client initialization
            self._client = OpenSearch(
                hosts=[{"host": settings.OPENSEARCH_AWS_HOST, "port": 443}],
                http_auth=awsauth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                timeout=60,
            )
            # Bedrock client.
            # It will inherit the credentials from the 'session' which was initialized
            # without AWS_SESSION_TOKEN in the environment.
            self._bedrock_client = session.client(
                "bedrock-runtime", region_name=aws_region
            )

        except Exception as e:
            logger.error(f"⚠️  Failed to initialize OpenSearch or Bedrock clients: {e}")
            logger.error(f"⚠️  Exception type: {type(e)}")
            import traceback

            logger.error(f"⚠️  Traceback: {traceback.format_exc()}")
            self._client = None
            self._bedrock_client = None
            # Re-raise to prevent the application from starting with uninitialized clients
            raise

    def is_available(self) -> bool:
        """Check if OpenSearch service is available."""
        # Check for both clients now that Bedrock is no longer a mock
        return self._client is not None and self._bedrock_client is not None

    def embed_query(self, text: str) -> List[float]:
        """
        Embed query using Bedrock Titan.

        Args:
            text: Text to embed

        Returns:
            List of embedding values

        Raises:
            RuntimeError: If Bedrock client is not initialized
        """
        if not self._bedrock_client:
            logger.error(
                "🔍 DEBUG: Bedrock client not initialized in embed_query. Attempting re-initialization."
            )
            self._initialize_clients()  # Try to re-initialize if not set
            if not self._bedrock_client:
                raise RuntimeError(
                    "Bedrock client not initialized after re-attempt in embed_query."
                )

        body = {"inputText": text}
        resp = self._bedrock_client.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        raw = resp["body"].read()
        obj = json.loads(raw)

        if "embedding" in obj:
            return obj["embedding"]
        elif "embeddings" in obj:
            return obj["embeddings"][0]
        else:
            raise RuntimeError(f"Unexpected embedding response: {obj}")

    @staticmethod
    def format_authors(authors_data) -> str:
        """
        Convert authors from list to formatted string.
        Handles both list and string inputs from OpenSearch.
        """
        if not authors_data:
            return ""
        if isinstance(authors_data, list):
            # Join list items with ", " separator
            return ", ".join(str(author) for author in authors_data if author)
        elif isinstance(authors_data, str):
            return authors_data
        else:
            return str(authors_data)

    def search_docs_with_embedding(
        self, expanded_query: str, k: Optional[int] = None
    ) -> List[dict]:
        """
        Search documents using vector similarity with expanded query.

        Args:
            expanded_query: Query text to search for
            k: Maximum number of results to return

        Returns:
            List of search results

        Raises:
            RuntimeError: If OpenSearch or Bedrock client is not initialized
        """
        if not self._client or not self._bedrock_client:
            # Re-initialize if clients are not available (e.g., after an error)
            self._initialize_clients()
            if not self._client or not self._bedrock_client:
                raise RuntimeError(
                    "OpenSearch or Bedrock client not initialized after re-attempt"
                )

        if k is None:
            k = settings.OPENSEARCH_TOP_K

        try:
            # Get embedding for search query
            q_emb = self.embed_query(expanded_query)

            body = {
                "size": k,
                "query": {"knn": {"embedding": {"vector": q_emb, "k": k}}},
            }
            resp = self._client.search(index=settings.OPENSEARCH_DOC_INDEX, body=body)
            return resp.get("hits", {}).get("hits", [])
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def transform_search_results(self, hits: List[dict]) -> List[Article]:
        """
        Transform OpenSearch search results to Article objects.

        Args:
            hits: Raw search results from OpenSearch

        Returns:
            List of Article objects
        """
        articles = []

        for hit in hits:
            try:
                source = hit.get("_source", {})
                article = Article(
                    id=str(source.get("id", "")),
                    title=source.get("title", ""),
                    abstract=source.get("abstract", ""),
                    doi=source.get("doi")
                    or source.get("doc_id"),  # Use doc_id as fallback for DOI
                    article_doi=source.get("article_doi"),
                    date=source.get("date"),
                    authors=self.format_authors(source.get("authors")),
                    journal=source.get("journal"),
                    score=hit.get("_score"),
                )
                articles.append(article)
            except Exception as e:
                logger.error(f"Error transforming search result: {e}")
                continue

        return articles

    def deduplicate_articles(self, articles: List[Article]) -> List[Article]:
        """
        Helper function to remove duplicate articles based on lowercase title comparison.
        Keeps the first occurrence of each unique title.

        Args:
            articles: List of articles to deduplicate

        Returns:
            List of unique articles
        """
        seen_titles = set()
        unique_articles = []

        for article in articles:
            # Use lowercase title for comparison
            title_lower = article.title.lower().strip() if article.title else ""

            if title_lower and title_lower not in seen_titles:
                seen_titles.add(title_lower)
                unique_articles.append(article)
        return unique_articles
