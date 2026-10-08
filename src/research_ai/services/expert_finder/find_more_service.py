"""Queue a find-more expert-finder run."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from research_ai.constants import (
    EXPERT_FINDER_ENGINE_CONFIG_KEY,
    normalize_expert_finder_engine,
)
from research_ai.models import ExpertSearch

logger = logging.getLogger(__name__)

_RUNNING = (ExpertSearch.Status.PENDING, ExpertSearch.Status.PROCESSING)
_IDLE = (ExpertSearch.Status.COMPLETED, ExpertSearch.Status.FAILED)


class FindMoreSearchNotFoundError(LookupError):
    """No ``ExpertSearch`` row for the given id."""


class FindMoreAlreadyRunningError(RuntimeError):
    """Search is pending or processing and cannot accept another find-more."""


class FindMoreInvalidStateError(RuntimeError):
    """Search is not in a terminal state that allows find-more."""


class FindMoreEnqueueError(RuntimeError):
    """Broker refused the task; prior search state has been restored."""


@dataclass(frozen=True)
class FindMoreQueued:
    expert_search: ExpertSearch
    expert_count: int


def enqueue_find_more_search(
    *,
    search_id: str,
    query: str,
    config: dict[str, Any],
    is_pdf: bool,
    additional_context: str | None,
) -> None:
    from research_ai.tasks import run_expert_finder_search

    run_expert_finder_search.delay(
        search_id=search_id,
        query=query,
        config=config,
        is_pdf=is_pdf,
        additional_context=additional_context,
        append=True,
    )


class FindMoreService:
    """Lock, validate, enqueue, and roll back a find-more (append) run."""

    def __init__(self, enqueue: Callable[..., None] | None = None):
        self._enqueue = enqueue if enqueue is not None else enqueue_find_more_search

    def queue(
        self,
        search_id: int,
        *,
        expert_count: int,
        additional_context: str | None = None,
        engine: str | None = None,
    ) -> FindMoreQueued:
        with transaction.atomic():
            try:
                expert_search = ExpertSearch.objects.select_for_update().get(
                    id=search_id
                )
            except ExpertSearch.DoesNotExist as exc:
                raise FindMoreSearchNotFoundError("Expert search not found.") from exc
            if expert_search.status in _RUNNING:
                raise FindMoreAlreadyRunningError("Expert search is already running.")
            if expert_search.status not in _IDLE:
                raise FindMoreInvalidStateError(
                    "Expert search cannot find more in its current state."
                )

            prior_status = expert_search.status
            prior_progress = expert_search.progress
            prior_current_step = expert_search.current_step
            prior_error_message = expert_search.error_message
            prior_config = dict(expert_search.config or {})
            prior_additional_context = expert_search.additional_context

            config = dict(prior_config)
            config["expert_count"] = expert_count
            if engine is not None:
                config[EXPERT_FINDER_ENGINE_CONFIG_KEY] = (
                    normalize_expert_finder_engine(engine)
                )
            if additional_context is not None:
                ctx = (additional_context or "").strip()
                expert_search.additional_context = ctx
            else:
                ctx = (expert_search.additional_context or "").strip()

            expert_search.config = config
            expert_search.status = ExpertSearch.Status.PROCESSING
            expert_search.progress = 0
            expert_search.current_step = "Queued to find more experts"
            expert_search.error_message = ""
            expert_search.save(
                update_fields=[
                    "config",
                    "additional_context",
                    "status",
                    "progress",
                    "current_step",
                    "error_message",
                    "updated_date",
                ]
            )

        is_pdf = expert_search.input_type == ExpertSearch.InputType.PDF
        try:
            self._enqueue(
                search_id=str(expert_search.id),
                query=expert_search.query,
                config=config,
                is_pdf=is_pdf,
                additional_context=ctx or None,
            )
        except Exception as exc:
            logger.exception(
                "could not queue find-more for expert search %s", expert_search.id
            )
            ExpertSearch.objects.filter(
                id=expert_search.id,
                status=ExpertSearch.Status.PROCESSING,
            ).update(
                status=prior_status,
                progress=prior_progress,
                current_step=prior_current_step,
                error_message=prior_error_message,
                config=prior_config,
                additional_context=prior_additional_context,
            )
            raise FindMoreEnqueueError(
                "Could not queue find-more expert search."
            ) from exc

        return FindMoreQueued(expert_search=expert_search, expert_count=expert_count)
