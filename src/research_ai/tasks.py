import logging
from datetime import datetime
from uuid import UUID

from researchhub.celery import app

logger = logging.getLogger(__name__)


def _update_search_progress(
    search_id: str, percent: int, message: str, status: str = "processing"
):
    """Update ExpertSearch progress in DB (for use from Celery)."""
    from research_ai.models import ExpertSearch

    try:
        ExpertSearch.objects.filter(id=UUID(search_id)).update(
            progress=percent,
            current_step=message[:512],
            status=status,
        )
    except Exception as e:
        logger.warning("Failed to update expert search progress: %s", e)


@app.task(bind=True)
def process_expert_search_task(
    self,
    search_id: str,
    query: str,
    config: dict,
    *,
    excluded_expert_names: list | None = None,
    is_pdf: bool = False,
):
    """
    Background task to process an expert search.

    Args:
        search_id: ExpertSearch UUID (string).
        query: Research description or document text.
        config: Dict with expert_count, expertise_level, region, state, gender.
        excluded_expert_names: Optional list of expert names to exclude.
        is_pdf: True if query was extracted from PDF.
    """
    from research_ai.models import ExpertSearch
    from research_ai.services.expert_finder_service import ExpertFinderService

    def progress_callback(sid: str, percent: int, message: str):
        status = "completed" if percent == 100 else "processing"
        _update_search_progress(sid, percent, message, status=status)
        try:
            self.update_state(
                state="PROGRESS", meta={"progress": percent, "status": message}
            )
        except Exception:
            pass

    try:
        logger.info("Starting expert finder for search_id=%s", search_id)
        _update_search_progress(
            search_id, 5, "Initializing expert search...", status="processing"
        )

        service = ExpertFinderService()
        start_time = datetime.utcnow()

        result = service.process_expert_search(
            search_id=search_id,
            query=query,
            config=config,
            excluded_expert_names=excluded_expert_names or [],
            is_pdf=is_pdf,
            progress_callback=progress_callback,
        )

        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds()

        report_urls = result.get("report_urls", {})
        ExpertSearch.objects.filter(id=UUID(search_id)).update(
            status="completed",
            progress=100,
            current_step="Expert search completed!",
            expert_results=result.get("experts", []),
            expert_count=result.get("expert_count", 0),
            report_pdf_url=report_urls.get("pdf", ""),
            report_csv_url=report_urls.get("csv", ""),
            processing_time=processing_time,
            completed_at=end_time,
            llm_model=result.get("llm_model", ""),
        )

        logger.info(
            "Expert finder completed for search_id=%s, experts=%s, time=%.2fs",
            search_id,
            result.get("expert_count", 0),
            processing_time,
        )
        return result

    except Exception as e:
        logger.exception("Expert finder failed for search_id=%s: %s", search_id, e)
        error_message = str(e)
        _update_search_progress(
            search_id,
            0,
            f"Processing failed: {error_message}",
            status="failed",
        )
        ExpertSearch.objects.filter(id=UUID(search_id)).update(
            status="failed",
            error_message=error_message[:10000],
        )
        raise
