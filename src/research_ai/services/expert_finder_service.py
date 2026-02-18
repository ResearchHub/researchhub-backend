import logging
import re
import urllib.request
from typing import Any, Callable

import fitz
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

from research_ai.models import ExpertSearch
from research_ai.prompts.expert_finder_prompts import (
    build_system_prompt,
    build_user_prompt,
)
from research_ai.services.bedrock_llm_service import BedrockLLMService
from research_ai.services.progress_service import ProgressService, TaskType
from research_ai.services.report_generator_service import (
    generate_csv_file,
    generate_pdf_report,
    upload_report_to_storage,
)
from researchhub_document.related_models.constants.document_type import PAPER

logger = logging.getLogger(__name__)


def get_document_content(unified_doc, input_type: str = "abstract"):
    """
    Extract content from UnifiedDocument for expert finder.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance.
        input_type: "abstract" (default), "pdf", "custom_query", or "full_content".

    Returns:
        tuple: (content_text, content_type) where content_type is one of
               "abstract", "pdf", "full_content".

    Raises:
        ValueError: If requested content is not available.
    """

    if unified_doc.document_type == PAPER:
        paper = unified_doc.paper
        if input_type == "pdf" and paper.pdf_url:
            text = _extract_text_from_pdf_url(paper.pdf_url)
            return (text, "pdf")
        if paper.abstract:
            return (paper.abstract, "abstract")
        if paper.pdf_url:
            text = _extract_text_from_pdf_url(paper.pdf_url)
            return (text, "pdf")
        raise ValueError("Paper has no abstract or PDF available")

    # Discussion, Question, Preregistration, Grant, etc. – use post content
    post = unified_doc.posts.first()
    if not post:
        raise ValueError("Document has no post content")
    if getattr(post, "renderable_text", None):
        return (post.renderable_text, "full_content")
    try:
        full = post.get_full_markdown()
        if full:
            return (full, "full_content")
    except Exception:
        pass
    raise ValueError("Post has no content available")


def _extract_text_from_pdf_url(pdf_url: str) -> str:
    """Download PDF from URL and extract text using PyMuPDF."""

    try:
        with urllib.request.urlopen(pdf_url, timeout=60) as resp:
            pdf_bytes = resp.read()
    except Exception as e:
        logger.warning("Failed to download PDF from %s: %s", pdf_url[:80], e)
        raise ValueError(f"Could not download PDF: {e}") from e

    try:

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        for page in doc:
            parts.append(page.get_text())
        doc.close()
        text = "\n".join(parts)
        return text[:200000] if len(text) > 200000 else text
    except Exception as e:
        logger.warning("Failed to extract text from PDF: %s", e)
        raise ValueError(f"PDF text extraction failed: {e}") from e


class ExpertFinderService:
    def __init__(self):
        self.bedrock_llm = BedrockLLMService()
        self.progress_service = ProgressService()

    def process_expert_search(
        self,
        search_id: str,
        query: str,
        config: dict[str, Any],
        *,
        excluded_expert_names: list[str] | None = None,
        is_pdf: bool = False,
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Run expert finder: build prompts, call Bedrock, parse table, generate reports.

        All operations are synchronous (for use from Celery). Progress is published
        to Redis and optionally to progress_callback(search_id, percent, message).

        is_pdf: Set True when query text was extracted from a PDF (affects prompt wording).
        """

        def publish(
            message: str,
            percent: int,
            status: str = ExpertSearch.Status.PROCESSING,
        ):
            status_val = status.value if hasattr(status, "value") else status
            self.progress_service.publish_progress_sync(
                TaskType.EXPERTS,
                search_id,
                {
                    "status": status_val,
                    "progress": percent,
                    "currentStep": message,
                    "type": (
                        "progress"
                        if status_val == ExpertSearch.Status.PROCESSING
                        else status_val
                    ),
                },
            )
            if progress_callback:
                progress_callback(search_id, percent, message)

        try:
            logger.info("Starting Expert Finder for search_id=%s", search_id)
            expert_count = config.get("expert_count", config.get("expertCount", 10))
            expertise_level_raw = config.get(
                "expertise_level", config.get("expertiseLevel", ["All Levels"])
            )
            if isinstance(expertise_level_raw, str):
                expertise_level = (
                    [expertise_level_raw] if expertise_level_raw else ["All Levels"]
                )
            elif expertise_level_raw:
                # Flatten to list of strings (avoid nested lists from JSON)
                expertise_level = []
                for x in expertise_level_raw:
                    if isinstance(x, str):
                        expertise_level.append(x)
                    elif isinstance(x, list):
                        expertise_level.extend(y for y in x if isinstance(y, str))
            else:
                expertise_level = ["All Levels"]
            region_filter = config.get("region", "All Regions")
            state_filter = config.get("state", "All States")
            gender_filter = config.get(
                "gender", config.get("genderPreference", "All Genders")
            )
            excluded = excluded_expert_names or []

            publish("Preparing expert search prompt...", 20)
            system_prompt = build_system_prompt(
                expert_count=expert_count,
                expertise_level=expertise_level,
                region_filter=region_filter,
                state_filter=state_filter,
                gender_filter=gender_filter,
                excluded_expert_names=excluded,
            )
            user_prompt = build_user_prompt(
                query=query,
                expert_count=expert_count,
                expertise_level=expertise_level,
                region_filter=region_filter,
                gender_filter=gender_filter,
                is_pdf=is_pdf,
            )

            publish("Initiating AI search...", 50)
            llm_response = self.bedrock_llm.invoke(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            logger.info("LLM response length: %s", len(llm_response))

            publish("Parsing expert recommendations...", 70)
            experts = self._parse_markdown_table(llm_response)
            logger.info("Parsed %s experts", len(experts))

            publish("Generating PDF report...", 80)
            pdf_bytes = generate_pdf_report(experts, query, config)
            publish("Generating CSV file...", 88)
            csv_bytes = generate_csv_file(experts)

            publish("Uploading results to storage...", 94)
            pdf_url = upload_report_to_storage(
                search_id, pdf_bytes, "pdf", "application/pdf"
            )
            csv_url = upload_report_to_storage(search_id, csv_bytes, "csv", "text/csv")

            result = {
                "search_id": search_id,
                "status": ExpertSearch.Status.COMPLETED,
                "query": query,
                "config": config,
                "experts": experts,
                "report_urls": {"pdf": pdf_url, "csv": csv_url},
                "expert_count": len(experts),
                "llm_model": self.bedrock_llm.model_id,
            }
            publish(
                "Expert search complete!", 100, status=ExpertSearch.Status.COMPLETED
            )
            if progress_callback:
                progress_callback(search_id, 100, "Expert search complete!")
            return result

        except Exception as e:
            error_message = f"Expert search processing failed: {str(e)}"
            logger.exception(error_message)
            publish(error_message, 0, status=ExpertSearch.Status.FAILED)
            if progress_callback:
                progress_callback(search_id, 0, error_message)
            raise

    def _extract_citations(self, text: str) -> tuple[str, list[dict[str, str]]]:
        """Extract markdown links [text](url) from notes; return (cleaned_text, citations)."""
        citations = []
        citation_pattern = r"\[([^\]]+)\]\(([^)]*)\)"
        for m in re.finditer(citation_pattern, text):
            raw_url = (m.group(2) or "").strip()
            if not raw_url:
                continue
            url = self._clean_url(raw_url)
            citations.append({"text": m.group(1), "url": url})
        cleaned = re.sub(citation_pattern, "", text)
        cleaned = re.sub(r"\(\)", "", cleaned).strip()
        return cleaned, citations

    def _clean_url(self, url: str) -> str:
        """Remove UTM and tracking query params."""
        if "?" not in url:
            return url
        base, qs = url.split("?", 1)
        params = [p for p in qs.split("&") if not p.startswith("utm_")]
        return f"{base}?{'&'.join(params)}" if params else base

    def _parse_markdown_table(self, markdown_text: str) -> list[dict[str, Any]]:
        """Parse markdown table from LLM response into list of expert dicts."""
        experts = []
        lines = markdown_text.split("\n")
        table_lines = []
        in_table = False
        for line in lines:
            if "|" in line:
                if re.match(r"^\s*\|[\s\-:]+\|", line):
                    continue
                table_lines.append(line)
                in_table = True
            elif in_table and line.strip() == "":
                break

        if len(table_lines) < 2:
            logger.warning("No valid markdown table in LLM response")
            return []

        header = table_lines[0]
        columns = [c.strip() for c in header.split("|") if c.strip()]
        column_map = {}
        for i, col in enumerate(columns):
            col_lower = col.lower()
            if "name" in col_lower:
                column_map["name"] = i
            elif "title" in col_lower:
                column_map["title"] = i
            elif "affiliation" in col_lower or "institution" in col_lower:
                column_map["affiliation"] = i
            elif "expertise" in col_lower:
                column_map["expertise"] = i
            elif "email" in col_lower or "contact" in col_lower:
                column_map["email"] = i
            elif "note" in col_lower:
                column_map["notes"] = i

        for line in table_lines[1:]:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) < 5:
                continue
            notes_raw = (
                cells[column_map["notes"]]
                if "notes" in column_map and len(cells) > column_map.get("notes", 5)
                else ""
            )
            notes_cleaned, citations = self._extract_citations(notes_raw)
            expert = {
                "name": (
                    cells[column_map.get("name", 0)] if "name" in column_map else ""
                ),
                "title": (
                    cells[column_map.get("title", 1)] if "title" in column_map else ""
                ),
                "affiliation": (
                    cells[column_map["affiliation"]]
                    if "affiliation" in column_map
                    else ""
                ),
                "expertise": (
                    cells[column_map["expertise"]] if "expertise" in column_map else ""
                ),
                "email": (
                    cells[column_map.get("email", 4)] if "email" in column_map else ""
                ),
                "notes": notes_cleaned,
                "sources": citations if citations else [],
            }
            email = (expert["email"] or "").strip()
            try:
                EmailValidator()(email)
            except ValidationError:
                logger.warning("Skipping expert %s: no valid email", expert["name"])
                continue
            experts.append(expert)

        return experts
