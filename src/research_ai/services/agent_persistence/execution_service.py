"""Execution creation and atomic claim services."""

from collections.abc import Callable

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from research_ai.models import (
    AgentConversation,
    AgentConversationMessage,
    AgentExecution,
    AgentExecutionMessage,
)
from research_ai.services.agent_persistence.recorder import DatabaseAgentRecorder
from research_ai.services.usage_budget.reservation import reservation_deadline

RecorderFactory = Callable[..., DatabaseAgentRecorder]


class AgentConversationBusyError(RuntimeError):
    """Raised when a linear conversation already has an active execution."""


class AgentStaleRetryError(RuntimeError):
    """Raised when a retry targets an attempt a later turn has moved past."""


class AgentExecutionService:
    def __init__(self, *, recorder_factory: RecorderFactory | None = None):
        self.recorder_factory = (
            DatabaseAgentRecorder if recorder_factory is None else recorder_factory
        )

    @staticmethod
    def _validate_relationships(
        conversation: AgentConversation,
        *,
        trigger_message: AgentConversationMessage | None,
        context_parent: AgentExecution | None,
        retry_of: AgentExecution | None,
        replaces_output_of: AgentExecution | None,
    ) -> None:
        related = [context_parent, retry_of, replaces_output_of]
        if any(
            item is not None and item.conversation_id != conversation.id
            for item in related
        ):
            raise ValueError("agent execution relationships cross conversations")
        if (
            trigger_message is not None
            and trigger_message.conversation_id != conversation.id
        ):
            raise ValueError("trigger message belongs to another conversation")

    @staticmethod
    def _ensure_no_active_execution(conversation: AgentConversation) -> None:
        if conversation.executions.filter(
            status__in=[
                AgentExecution.Status.PENDING,
                AgentExecution.Status.RUNNING,
            ]
        ).exists():
            raise AgentConversationBusyError(
                "agent conversation already has an active execution"
            )

    @staticmethod
    def _ensure_retry_target_is_latest(
        *,
        retry_of: AgentExecution | None,
        replaces_output_of: AgentExecution | None,
        max_attempt: int,
    ) -> None:
        """Refuse to retry an attempt a later turn has already continued past.

        A retry inherits its target's ``context_parent`` but takes the highest
        attempt, and continuation reads the highest attempt. Allowing an older
        target would make a branch that never saw the turns since canonical,
        dropping them from the model's view while the chat still shows them.
        """
        for target in (retry_of, replaces_output_of):
            if target is not None and target.attempt < max_attempt:
                raise AgentStaleRetryError(
                    "agent execution has been superseded by a later attempt"
                )

    def _create_execution(
        self,
        conversation: AgentConversation,
        *,
        status: str,
        provider: str,
        model: str,
        configuration: dict | None,
        system_prompt: str,
        trigger_message: AgentConversationMessage | None,
        context_parent: AgentExecution | None,
        retry_of: AgentExecution | None,
        publish_assistant_message: bool,
        replaces_output_of: AgentExecution | None,
    ) -> AgentExecution:
        self._validate_relationships(
            conversation,
            trigger_message=trigger_message,
            context_parent=context_parent,
            retry_of=retry_of,
            replaces_output_of=replaces_output_of,
        )
        now = timezone.now()
        with transaction.atomic():
            locked = AgentConversation.objects.select_for_update().get(
                id=conversation.id
            )
            self._ensure_no_active_execution(locked)
            max_attempt = (
                AgentExecution.objects.filter(conversation=locked).aggregate(
                    value=Max("attempt")
                )["value"]
                or 0
            )
            # Checked here, not in the caller: the lock this block holds is what
            # keeps a turn from landing between the check and the insert.
            self._ensure_retry_target_is_latest(
                retry_of=retry_of,
                replaces_output_of=replaces_output_of,
                max_attempt=max_attempt,
            )
            timestamps = (
                {"started_at": now, "last_activity_at": now}
                if status == AgentExecution.Status.RUNNING
                else {}
            )
            return AgentExecution.objects.create(
                conversation=locked,
                status=status,
                attempt=max_attempt + 1,
                context_parent=context_parent,
                retry_of=retry_of,
                replaces_output_of=replaces_output_of,
                trigger_message=trigger_message,
                provider=provider,
                model=model,
                configuration=configuration if configuration is not None else {},
                system_prompt=system_prompt,
                publish_output_to_chat=publish_assistant_message,
                **timestamps,
            )

    def start(
        self,
        conversation: AgentConversation,
        *,
        provider: str = "",
        model: str = "",
        configuration: dict | None = None,
        system_prompt: str = "",
        trigger_message: AgentConversationMessage | None = None,
        context_parent: AgentExecution | None = None,
        retry_of: AgentExecution | None = None,
        initial_prompt_provenance: str = AgentExecutionMessage.Provenance.BACKEND,
        publish_assistant_message: bool = False,
        replaces_output_of: AgentExecution | None = None,
    ) -> DatabaseAgentRecorder:
        execution = self._create_execution(
            conversation,
            status=AgentExecution.Status.RUNNING,
            provider=provider,
            model=model,
            configuration=configuration,
            system_prompt=system_prompt,
            trigger_message=trigger_message,
            context_parent=context_parent,
            retry_of=retry_of,
            publish_assistant_message=publish_assistant_message,
            replaces_output_of=replaces_output_of,
        )
        return self.recorder_factory(
            execution,
            initial_prompt_provenance=initial_prompt_provenance,
            publish_assistant_message=publish_assistant_message,
        )

    def create_pending(
        self,
        conversation: AgentConversation,
        *,
        provider: str = "",
        model: str = "",
        configuration: dict | None = None,
        system_prompt: str = "",
        trigger_message: AgentConversationMessage | None = None,
        context_parent: AgentExecution | None = None,
        retry_of: AgentExecution | None = None,
        publish_assistant_message: bool = False,
    ) -> AgentExecution:
        """Create a queued attempt that a worker can claim later."""
        return self._create_execution(
            conversation,
            status=AgentExecution.Status.PENDING,
            provider=provider,
            model=model,
            configuration=configuration,
            system_prompt=system_prompt,
            trigger_message=trigger_message,
            context_parent=context_parent,
            retry_of=retry_of,
            publish_assistant_message=publish_assistant_message,
            replaces_output_of=None,
        )

    def claim_pending(
        self,
        execution: AgentExecution,
        *,
        initial_prompt_provenance: str = AgentExecutionMessage.Provenance.BACKEND,
        publish_assistant_message: bool | None = None,
    ) -> DatabaseAgentRecorder | None:
        """Atomically claim a queued attempt; return ``None`` if already claimed."""
        now = timezone.now()
        updates = {
            "status": AgentExecution.Status.RUNNING,
            "started_at": now,
            "last_activity_at": now,
        }
        if execution.usage_reservation_expires_at is not None:
            updates["usage_reservation_expires_at"] = reservation_deadline(now)
        if publish_assistant_message is not None:
            updates["publish_output_to_chat"] = publish_assistant_message
        claimed = AgentExecution.objects.filter(
            id=execution.id, status=AgentExecution.Status.PENDING
        ).update(**updates)
        if not claimed:
            return None
        execution.refresh_from_db()
        return self.recorder_factory(
            execution,
            initial_prompt_provenance=initial_prompt_provenance,
            publish_assistant_message=publish_assistant_message,
        )
