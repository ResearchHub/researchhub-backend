"""Full execution-detail read service."""

from research_ai.models import AgentExecution


class AgentRunDetailsService:
    def get(self, execution: AgentExecution) -> dict:
        execution.refresh_from_db()
        trace = [
            {
                "sequence": message.sequence,
                "execution_sequence": message.execution_sequence,
                "role": message.role,
                "provenance": message.provenance,
                "content": message.content,
                "stop_reason": message.provider_stop_reason,
                "usage": {
                    "input_tokens": message.input_tokens,
                    "output_tokens": message.output_tokens,
                    "cache_read_tokens": message.cache_read_tokens,
                    "cache_write_tokens": message.cache_write_tokens,
                },
                "latency_ms": message.latency_ms,
                "is_truncated": message.is_truncated,
                "original_size_bytes": message.original_size_bytes,
            }
            for message in execution.messages.order_by("execution_sequence")
        ]
        return {
            "id": execution.id,
            "conversation_id": execution.conversation_id,
            "attempt": execution.attempt,
            "status": execution.status,
            "provider": execution.provider,
            "model": execution.model,
            "configuration": execution.configuration,
            "system_prompt": execution.system_prompt,
            "iterations": execution.iterations,
            "usage": {
                "input_tokens": execution.input_tokens,
                "output_tokens": execution.output_tokens,
                "cache_read_tokens": execution.cache_read_tokens,
                "cache_write_tokens": execution.cache_write_tokens,
            },
            "total_latency_ms": execution.total_latency_ms,
            "duration_ms": execution.duration_ms,
            "stop_reason": execution.stop_reason,
            "final_output": execution.final_output,
            "failure": (
                {
                    "type": execution.error_type,
                    "message": execution.error_message,
                    "details": execution.error_details,
                }
                if execution.error_type
                else None
            ),
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
            "trace": trace,
        }
