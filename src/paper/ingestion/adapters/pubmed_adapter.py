"""
PubMed adapter for paper ingestion

Uses NCBI E-utilities for searching and fetching PubMed articles.
"""

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import quote

import structlog

from ..core.base_adapter import BaseAdapter

logger = structlog.get_logger(__name__)


class PubmedAdapter(BaseAdapter):
    """
    Adapter for PubMed papers using NCBI E-utilities

    API Documentation: https://www.ncbi.nlm.nih.gov/books/NBK25501/

    Requires API key for better rate limits:
    - Without key: 3 requests/second
    - With key: 10 requests/second
    """

    SOURCE_NAME = "pubmed"
    DEFAULT_RATE_LIMIT = "3/s"  # Without API key

    # E-utilities endpoints
    ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    def __init__(self, rate_limit: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize PubMed adapter

        Args:
            rate_limit: Override rate limit
            api_key: NCBI API key for increased rate limits
        """
        super().__init__(rate_limit=rate_limit, api_key=api_key)

        # Adjust rate limit if API key is provided
        if self.api_key and not rate_limit:
            self.rate_limit = "10/s"
            self._parse_rate_limit()
            logger.info("Using NCBI API key, rate limit increased to 10/s")

    def _get_auth_headers(self) -> Dict[str, str]:
        """Add API key to request parameters if available"""
        if self.api_key:
            return {"api_key": self.api_key}
        return {}

    def fetch_recent(self, hours: int = 24) -> Iterator[Dict[str, Any]]:
        """
        Fetch recent papers from PubMed

        Args:
            hours: Number of hours to look back

        Yields:
            Batches of raw response data
        """
        # Calculate date range
        if hours <= 24:
            date_filter = "last_1_days"
        elif hours <= 48:
            date_filter = "last_2_days"
        elif hours <= 72:
            date_filter = "last_3_days"
        elif hours <= 168:  # 7 days
            date_filter = "last_7_days"
        elif hours <= 720:  # 30 days
            date_filter = "last_30_days"
        else:
            # For longer periods, use date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(hours=hours)
            yield from self.fetch_date_range(start_date, end_date)
            return

        # Build search query for recent papers
        # Focus on preprints and recent additions
        query = f'("{date_filter}"[CRDT] OR "{date_filter}"[EDAT]) AND (preprint[pt] OR "ahead of print"[pt])'

        yield from self._search_and_fetch(query, f"recent_{hours}h")

    def fetch_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> Iterator[Dict[str, Any]]:
        """
        Fetch papers within a date range

        Args:
            start_date: Start of date range
            end_date: End of date range

        Yields:
            Batches of raw response data
        """
        # Format dates for PubMed (YYYY/MM/DD)
        from_date = start_date.strftime("%Y/%m/%d")
        to_date = end_date.strftime("%Y/%m/%d")

        # Build query with date range
        query = f'("{from_date}"[CRDT]:"{to_date}"[CRDT]) OR ("{from_date}"[EDAT]:"{to_date}"[EDAT])'

        yield from self._search_and_fetch(query, f"{from_date}_{to_date}")

    def _search_and_fetch(
        self, query: str, query_label: str
    ) -> Iterator[Dict[str, Any]]:
        """
        Search PubMed and fetch results

        Uses the E-utilities two-step process:
        1. ESearch to get PMIDs
        2. EFetch to get full records

        Args:
            query: PubMed search query
            query_label: Label for this query

        Yields:
            Batches of raw response data
        """
        # Step 1: Search to get PMIDs and optionally use history server
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": 0,  # Just get count first
            "usehistory": "y",
            "retmode": "json",
        }

        if self.api_key:
            search_params["api_key"] = self.api_key

        # Get total count and WebEnv/QueryKey for history server
        search_response = self._make_request(self.ESEARCH_URL, params=search_params)
        search_data = search_response.json()

        esearch_result = search_data.get("esearchresult", {})
        total_count = int(esearch_result.get("count", 0))
        webenv = esearch_result.get("webenv")
        query_key = esearch_result.get("querykey")

        if total_count == 0:
            logger.info(f"No results found for query: {query}")
            return

        logger.info(f"Found {total_count} papers for query: {query_label}")

        # Step 2: Fetch records in batches using history server
        batch_size = 200  # Max recommended by NCBI
        retstart = 0

        while retstart < total_count:
            # Fetch batch of full records
            fetch_params = {
                "db": "pubmed",
                "retmode": "xml",
                "rettype": "abstract",
                "retstart": retstart,
                "retmax": min(batch_size, total_count - retstart),
                "WebEnv": webenv,
                "query_key": query_key,
            }

            if self.api_key:
                fetch_params["api_key"] = self.api_key

            fetch_response = self._make_request(self.EFETCH_URL, params=fetch_params)

            papers_in_batch = min(batch_size, total_count - retstart)

            yield {
                "source": "pubmed_efetch",
                "query": query,
                "query_label": query_label,
                "batch_start": retstart,
                "batch_size": papers_in_batch,
                "total_count": total_count,
                "response": fetch_response.text,
                "count": papers_in_batch,
            }

            retstart += batch_size
            logger.info(
                f"Fetched {min(retstart, total_count)}/{total_count} PubMed papers"
            )

    def parse_response(self, response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse PubMed XML response into standard format

        Args:
            response_data: Raw response with XML in 'response' field

        Returns:
            List of parsed papers
        """
        papers = []
        xml_data = response_data.get("response", "")

        try:
            root = ET.fromstring(xml_data)

            # Parse each PubmedArticle
            for article in root.findall(".//PubmedArticle"):
                try:
                    paper = self._parse_pubmed_article(article)
                    if paper:
                        papers.append(paper)
                except Exception as e:
                    logger.error(f"Error parsing PubMed article: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error parsing PubMed XML: {e}")

        logger.info(f"Parsed {len(papers)} papers from PubMed response")
        return papers

    def _parse_pubmed_article(self, article: ET.Element) -> Optional[Dict[str, Any]]:
        """
        Parse a single PubmedArticle element

        Args:
            article: XML Element for PubmedArticle

        Returns:
            Parsed paper dictionary
        """
        # Get MedlineCitation
        medline_citation = article.find("MedlineCitation")
        if medline_citation is None:
            return None

        # Extract PMID
        pmid_elem = medline_citation.find("PMID")
        pmid = pmid_elem.text if pmid_elem is not None else None

        # Get Article element
        article_elem = medline_citation.find("Article")
        if article_elem is None:
            return None

        # Extract title
        article_title = article_elem.find("ArticleTitle")
        title = article_title.text if article_title is not None else ""

        # Extract abstract
        abstract_elem = article_elem.find("Abstract")
        abstract = ""
        if abstract_elem is not None:
            abstract_texts = []
            for abstract_text in abstract_elem.findall("AbstractText"):
                text = abstract_text.text or ""
                label = abstract_text.get("Label")
                if label:
                    abstract_texts.append(f"{label}: {text}")
                else:
                    abstract_texts.append(text)
            abstract = " ".join(abstract_texts)

        # Extract authors
        authors = []
        author_list = article_elem.find("AuthorList")
        if author_list is not None:
            for author in author_list.findall("Author"):
                author_dict = {}

                lastname = author.find("LastName")
                if lastname is not None:
                    author_dict["family"] = lastname.text

                forename = author.find("ForeName")
                if forename is not None:
                    author_dict["given"] = forename.text

                # Full name
                if "family" in author_dict and "given" in author_dict:
                    author_dict["name"] = (
                        f"{author_dict['given']} {author_dict['family']}"
                    )

                # Affiliation
                affiliation = author.find(".//Affiliation")
                if affiliation is not None:
                    author_dict["affiliation"] = affiliation.text

                # ORCID
                identifier = author.find(".//Identifier[@Source='ORCID']")
                if identifier is not None:
                    author_dict["orcid"] = identifier.text

                if author_dict:
                    authors.append(author_dict)

        # Extract publication date
        pub_date = None
        article_date = article_elem.find(".//ArticleDate")
        if article_date is not None:
            year = article_date.find("Year")
            month = article_date.find("Month")
            day = article_date.find("Day")
            if year is not None:
                date_parts = [year.text]
                if month is not None:
                    date_parts.append(month.text.zfill(2))
                    if day is not None:
                        date_parts.append(day.text.zfill(2))
                pub_date = "-".join(date_parts)

        # If no ArticleDate, try PubDate
        if not pub_date:
            journal_issue = article_elem.find(".//JournalIssue")
            if journal_issue is not None:
                pub_date_elem = journal_issue.find("PubDate")
                if pub_date_elem is not None:
                    year = pub_date_elem.find("Year")
                    if year is not None:
                        pub_date = year.text

        # Extract DOI
        doi = None
        elocation_id = article_elem.find(".//ELocationID[@EIdType='doi']")
        if elocation_id is not None:
            doi = elocation_id.text
        else:
            # Try ArticleId
            article_id = article.find(".//ArticleId[@IdType='doi']")
            if article_id is not None:
                doi = article_id.text

        # Extract PMC ID
        pmcid = None
        pmc_elem = article.find(".//ArticleId[@IdType='pmc']")
        if pmc_elem is not None:
            pmcid = pmc_elem.text

        # Journal information
        journal = article_elem.find(".//Journal")
        journal_title = ""
        if journal is not None:
            title_elem = journal.find("Title")
            if title_elem is not None:
                journal_title = title_elem.text

        # Publication type
        pub_types = []
        for pub_type in article_elem.findall(".//PublicationType"):
            pub_types.append(pub_type.text)

        # Check if it's a preprint
        is_preprint = any("Preprint" in pt for pt in pub_types)

        # MeSH terms
        mesh_terms = []
        mesh_heading_list = medline_citation.find("MeshHeadingList")
        if mesh_heading_list is not None:
            for mesh_heading in mesh_heading_list.findall("MeshHeading"):
                descriptor = mesh_heading.find("DescriptorName")
                if descriptor is not None:
                    mesh_terms.append(descriptor.text)

        # Build URLs
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None

        # PMC URL if available
        pdf_url = None
        if pmcid:
            pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"

        paper = {
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "published_date": pub_date,
            "doi": doi,
            "pmid": int(pmid) if pmid else None,
            "pmcid": pmcid,
            "source_id": f"pmid:{pmid}",
            "url": url,
            "pdf_url": pdf_url,
            "journal": journal_title,
            "is_preprint": is_preprint,
            "metadata": {
                "source": "pubmed",
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "journal": journal_title,
                "publication_types": pub_types,
                "mesh_terms": mesh_terms,
                "is_preprint": is_preprint,
            },
        }

        return paper

    def fetch_by_pmid(self, pmid: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single paper by PMID

        Args:
            pmid: PubMed ID

        Returns:
            Raw response data
        """
        params = {"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"}

        if self.api_key:
            params["api_key"] = self.api_key

        try:
            response = self._make_request(self.EFETCH_URL, params=params)

            return {
                "source": "pubmed_efetch",
                "pmid": pmid,
                "response": response.text,
                "count": 1,
            }
        except Exception as e:
            logger.error(f"Error fetching PubMed paper {pmid}: {e}")
            return None

    def search(self, query: str, max_results: int = 100) -> List[str]:
        """
        Search PubMed and return PMIDs

        Args:
            query: PubMed search query
            max_results: Maximum number of results

        Returns:
            List of PMIDs
        """
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
        }

        if self.api_key:
            params["api_key"] = self.api_key

        try:
            response = self._make_request(self.ESEARCH_URL, params=params)
            data = response.json()

            id_list = data.get("esearchresult", {}).get("idlist", [])
            return id_list

        except Exception as e:
            logger.error(f"Error searching PubMed: {e}")
            return []
