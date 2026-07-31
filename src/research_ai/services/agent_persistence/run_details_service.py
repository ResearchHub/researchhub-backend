"""Full execution-detail read service."""

from dataclasses import dataclass
from datetime import datetime

from research_ai.models import AgentExecution


@dataclass(frozen=True)
class AgentTokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None


@dataclass(frozen=True)
class AgentRunFailure:
    type: str
    message: str
    details: dict


@dataclass(frozen=True)
class AgentTraceDetails:
    sequence: int
    execution_sequence: int
    role: str
    provenance: str
    content: list[dict]
    stop_reason: str
    usage: AgentTokenUsage
    latency_ms: int | None
    is_truncated: bool
    original_size_bytes: int | None


@dataclass(frozen=True)
class AgentRunDetails:
    id: int
    conversation_id: int
    attempt: int
    status: str
    provider: str
    model: str
    configuration: dict
    system_prompt: str
    iterations: int
    usage: AgentTokenUsage
    total_latency_ms: int | None
    duration_ms: int | None
    stop_reason: str
    final_output: dict
    failure: AgentRunFailure | None
    started_at: datetime | None
    finished_at: datetime | None
    trace: list[AgentTraceDetails]


class AgentRunDetailsService:
    def get(self, execution: AgentExecution) -> AgentRunDetails:
        execution.refresh_from_db()
        trace = [
            AgentTraceDetails(
                sequence=message.sequence,
                execution_sequence=message.execution_sequence,
                role=message.role,
                provenance=message.provenance,
                content=message.content,
                stop_reason=message.provider_stop_reason,
                usage=AgentTokenUsage(
                    input_tokens=message.input_tokens,
                    output_tokens=message.output_tokens,
                    cache_read_tokens=message.cache_read_tokens,
                    cache_write_tokens=message.cache_write_tokens,
                ),
                latency_ms=message.latency_ms,
                is_truncated=message.is_truncated,
                original_size_bytes=message.original_size_bytes,
            )
            for message in execution.messages.order_by("execution_sequence")
        ]
        return AgentRunDetails(
            id=execution.id,
            conversation_id=execution.conversation_id,
            attempt=execution.attempt,
            status=execution.status,
            provider=execution.provider,
            model=execution.model,
            configuration=execution.configuration,
            system_prompt=execution.system_prompt,
            iterations=execution.iterations,
            usage=AgentTokenUsage(
                input_tokens=execution.input_tokens,
                output_tokens=execution.output_tokens,
                cache_read_tokens=execution.cache_read_tokens,
                cache_write_tokens=execution.cache_write_tokens,
            ),
            total_latency_ms=execution.total_latency_ms,
            duration_ms=execution.duration_ms,
            stop_reason=execution.stop_reason,
            final_output=execution.final_output,
            failure=(
                AgentRunFailure(
                    type=execution.error_type,
                    message=execution.error_message,
                    details=execution.error_details,
                )
                if execution.error_type
                else None
            ),
            started_at=execution.started_at,
            finished_at=execution.finished_at,
            trace=trace,
        )
