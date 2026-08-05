"""The notebook chat assistant: research + note edits driven by user feedback.

One conversation per (note, user), workflow ``notebook_chat``. A turn is
split across two processes:

- ``submit_message`` (request path) resolves the conversation, appends the
  user's message, and creates the ``RUNNING`` execution via
  ``AgentChatService.prepare_turn`` -- so the chat shows the question
  immediately and the conversation is locked against concurrent turns -- then
  schedules the Celery task on commit.
- ``run_turn`` (worker path) rebuilds everything durable from the execution
  row (recorder, context lineage, system prompt, trigger message), composes
  the note + research toolset with the conversation owner's permissions, and
  drives ``Agent.continue_conversation``. The recorder persists the trace,
  marks the terminal status, and publishes the assistant's reply to the chat.

The agent acts strictly as the conversation's user and only on the
conversation's note: ``NoteToolset`` enforces note view/edit permissions per
call, so a viewer can chat and research but the edit tool refuses to write for
them, and it is scoped to the routed note, so the model cannot be talked into
touching another note the same user could access.
"""

import logging

from django.db import transaction

from note.related_models.note_model import Note
from research_ai.models import AgentConversation, AgentExecution
from research_ai.models.agent import AgentExecutionMessage
from research_ai.prompts.notebook_chat_prompts import build_notebook_chat_system_prompt
from research_ai.services.agent import (
    AgentRunError,
    AgentService,
    generator_model_ref,
    resolve_provider,
)
from research_ai.services.agent.providers.registry import generator_provider_name
from research_ai.services.agent_persistence import (
    AgentChatService,
    AgentContextService,
    AgentConversationService,
    DatabaseAgentRecorder,
    NoteAgentConversationService,
)
from research_ai.services.note_tools import NoteToolset
from research_ai.services.notebook_chat.config import NotebookChatConfig
from research_ai.services.notebook_chat.toolset import (
    NotebookWebSearchToolset,
    compose_notebook_toolset,
)
from research_ai.services.researcher_profile.openalex_tools import OpenAlexToolset
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

WORKFLOW = "notebook_chat"


class NotebookChatService:
    """Prepare and run notebook chat turns.

    Runtime collaborators are injectable for tests; in production they default
    to the settings-configured generator provider, OpenAlex client, Brave web
    search, and database persistence services.
    """

    def __init__(
        self,
        *,
        provider=None,
        oa_client: OpenAlex | None = None,
        web_search_client=None,
        chat_service: AgentChatService | None = None,
        conversation_service: AgentConversationService | None = None,
        note_conversation_service: NoteAgentConversationService | None = None,
        context_service: AgentContextService | None = None,
        config: NotebookChatConfig | None = None,
    ):
        self._provider = provider
        self._oa_client = oa_client
        self._web_search_client = web_search_client
        self.chat = AgentChatService() if chat_service is None else chat_service
        self.conversations = (
            AgentConversationService()
            if conversation_service is None
            else conversation_service
        )
        self.note_conversations = (
            NoteAgentConversationService()
            if note_conversation_service is None
            else note_conversation_service
        )
        self.contexts = (
            AgentContextService() if context_service is None else context_service
        )
        self._config = config

    @property
    def config(self) -> NotebookChatConfig:
        return self._config or NotebookChatConfig.from_settings()

    # -- request path -----------------------------------------------------

    def get_conversation(self, note: Note, user) -> AgentConversation | None:
        """The user's existing notebook chat conversation on ``note``, if any."""
        return (
            self.note_conversations.for_note(note)
            .filter(workflow=WORKFLOW, user=user)
            .first()
        )

    def get_or_create_conversation(self, note: Note, user) -> AgentConversation:
        conversation = self.get_conversation(note, user)
        if conversation is not None:
            return conversation
        with transaction.atomic():
            # Serialize concurrent first messages on the note row: without
            # this, each request creates its own conversation and the busy
            # check in ``prepare_turn`` -- which locks per conversation --
            # would happily run both turns against the note at once.
            Note.objects.select_for_update().get(id=note.id)
            conversation = self.get_conversation(note, user)
            if conversation is not None:
                return conversation
            conversation = self.conversations.create(user=user, workflow=WORKFLOW)
            self.note_conversations.attach(conversation, note)
            return conversation

    def submit_message(self, note: Note, user, text: str) -> AgentExecution:
        """Record the user's message and schedule the agent turn.

        Raises ``ValueError`` on an empty or oversized message and lets
        ``AgentConversationBusyError`` propagate when a turn is already
        running on the conversation (the API maps it to a 409).
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("message must not be empty")
        config = self.config
        if len(text) > config.max_message_chars:
            raise ValueError(f"message exceeds {config.max_message_chars} characters")

        conversation = self.get_or_create_conversation(note, user)
        prepared = self.chat.prepare_turn(
            conversation,
            text,
            provider=generator_provider_name(),
            model=generator_model_ref(),
            configuration={
                "max_iterations": config.max_iterations,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "note_id": note.id,
            },
            system_prompt=build_notebook_chat_system_prompt(note),
        )
        execution = prepared.execution

        # Imported here, not at module top: ``tasks`` imports this service, so
        # a top-level import would be a cycle.
        from research_ai.tasks import run_notebook_chat_turn_task

        transaction.on_commit(lambda: run_notebook_chat_turn_task.delay(execution.id))
        return execution

    # -- worker path ------------------------------------------------------

    def run_turn(self, execution_id: int) -> dict:
        """Drive one prepared execution to a terminal state.

        Everything the turn needs is rebuilt from the execution row, so the
        worker shares no in-memory state with the request that prepared it.
        Idempotent on redelivery: a row no longer ``RUNNING`` is skipped.
        """
        execution = AgentExecution.objects.select_related(
            "conversation", "conversation__user", "trigger_message"
        ).get(id=execution_id)
        if execution.status != AgentExecution.Status.RUNNING:
            logger.info(
                "notebook chat turn %s skipped: status is %s",
                execution_id,
                execution.status,
            )
            return {"execution_id": execution.id, "skipped": True}

        recorder = DatabaseAgentRecorder(
            execution,
            initial_prompt_provenance=AgentExecutionMessage.Provenance.HUMAN,
        )
        try:
            return self._run_turn(execution, recorder)
        except Exception as exc:
            # Terminal safety net: whatever escapes before or around the agent
            # loop (provider resolution, toolset build, a bug) still lands the
            # execution in FAILED -- a row stuck RUNNING blocks every later
            # turn on the conversation.
            logger.exception("notebook chat turn %s crashed", execution.id)
            if not recorder.terminal_observed:
                try:
                    recorder.on_run_failed(exc)
                except Exception:  # noqa: BLE001 - keep the original failure
                    logger.warning(
                        "could not finalize crashed notebook chat turn",
                        exc_info=True,
                    )
            return {"execution_id": execution.id, "error": str(exc)}

    def _run_turn(self, execution: AgentExecution, recorder) -> dict:
        conversation = execution.conversation
        note = self._note_for(conversation)
        trigger = execution.trigger_message
        if note is None or conversation.user is None or trigger is None:
            error = AgentRunError(
                "notebook chat execution is missing its note, user, or message"
            )
            recorder.on_run_failed(error)
            return {"execution_id": execution.id, "error": str(error)}

        provider = self._provider or resolve_provider(
            native_tools=frozenset({"web_search"})
        )
        toolset = compose_notebook_toolset(
            note_toolset=NoteToolset(user=conversation.user, note_ids={note.id}),
            openalex_toolset=OpenAlexToolset(client=self._oa_client or OpenAlex()),
            web_search_toolset=NotebookWebSearchToolset(client=self._web_search_client),
            native_tool_names=provider.native_tool_names,
        )
        config = self.config
        agent = AgentService(
            provider=provider, max_iterations=config.max_iterations
        ).create_agent(
            toolset,
            system_prompt=execution.system_prompt,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            recorder=recorder,
        )

        context = (
            self.contexts.reconstruct(execution.context_parent)
            if execution.context_parent_id
            else []
        )
        try:
            result = agent.continue_conversation(context, trigger.content)
        except AgentRunError as exc:
            # The loop already recorded the failure (status, error fields,
            # partial trace) through the recorder; report, don't re-raise.
            logger.warning("notebook chat turn %s failed: %s", execution.id, exc)
            return {"execution_id": execution.id, "error": str(exc)}
        return {
            "execution_id": execution.id,
            "stop_reason": result.stop_reason,
            "iterations": result.iterations,
            "final_text": result.final_text,
        }

    def _note_for(self, conversation: AgentConversation) -> Note | None:
        link = conversation.note_links.select_related("note").order_by("id").first()
        return link.note if link else None
