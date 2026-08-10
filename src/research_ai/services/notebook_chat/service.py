"""The notebook chat assistant: research + note edits driven by user feedback.

One conversation per (note, user), workflow ``notebook_chat``. A turn is
split across two processes:

- ``submit_message`` (request path) resolves the conversation, appends the
  user's message, and creates a ``PENDING`` execution via
  ``AgentChatService.prepare_turn`` -- so the chat shows the question
  immediately and the conversation is locked against concurrent turns -- then
  schedules the Celery task on commit. An execution the broker refuses to
  queue is failed on the spot rather than left holding the busy check.
- ``run_turn`` (worker path) atomically claims the execution (``PENDING`` ->
  ``RUNNING``), so a redelivered or duplicated task is a no-op, then rebuilds
  everything durable from the execution row (recorder, context lineage, the
  recorded model and generation config, system prompt, trigger message),
  composes the note + research toolset with
  the conversation owner's permissions, and drives
  ``Agent.continue_conversation``. The recorder persists the trace, marks the
  terminal status, and publishes the assistant's reply to the chat.

The agent acts strictly as the conversation's user and only on the
conversation's note: ``NoteToolset`` enforces note view/edit permissions per
call, so a viewer can chat and research but the edit tool refuses to write for
them, and it is scoped to the routed note, so the model cannot be talked into
touching another note the same user could access.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

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
    AgentExecutionCancelService,
    NoteAgentConversationService,
)
from research_ai.services.agent_persistence.activity import (
    conversation_activity_events,
)
from research_ai.services.note_tools import NoteToolset
from research_ai.services.notebook_chat.activity import (
    execution_phase,
    public_activity,
)
from research_ai.services.notebook_chat.config import NotebookChatConfig
from research_ai.services.notebook_chat.toolset import (
    NotebookWebSearchToolset,
    compose_notebook_toolset,
)
from research_ai.services.researcher_profile.openalex_tools import OpenAlexToolset
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

WORKFLOW = "notebook_chat"

# Activity projection scopes for ``NotebookChatService.representation``.
ACTIVITY_ALL = "all"
ACTIVITY_LIVE = "live"

# How long a settled turn stays in the live projection. A turn can settle and
# be displaced as newest by a fresh message between two polls -- cancel, then
# rephrase -- and the settled feed must still reach a client whose cached copy
# shows the turn mid-flight. The window needs only to outlast a polling
# interval; a client that stopped polling for longer is expected to refetch the
# full projection anyway. It also keeps a just-cancelled turn in scope while
# its worker unwinds, when trace rows can genuinely still land.
ACTIVITY_SETTLED_GRACE = timedelta(seconds=60)


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
        cancel_service: AgentExecutionCancelService | None = None,
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
        self.cancels = (
            AgentExecutionCancelService() if cancel_service is None else cancel_service
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

    def representation(
        self, conversation: AgentConversation, *, activity_scope: str = ACTIVITY_ALL
    ) -> dict:
        """The chat representation plus each turn's public activity feed.

        Activity is a notebook-chat presentation concern layered onto the
        workflow-neutral chat payload, so the generic service stays free of
        tool-specific knowledge.

        ``activity_scope`` trades completeness for cost. ``"all"`` projects
        activity for every execution and is what a client wants on first load.
        ``"live"`` projects it only for executions the client may not hold
        settled -- active turns, anything that settled within
        ``ACTIVITY_SETTLED_GRACE`` (a turn can settle and be displaced by a new
        message between two polls, and the client's cached feed would otherwise
        show it mid-flight forever), and the latest attempt, whose rendering
        can still change late when a delayed publication repair lands. The rest
        **omit the ``activity`` key entirely**. An absent key means "unchanged,
        keep what you have"; it is deliberately not an empty list, which would
        be indistinguishable from a turn that used no tools. This is what keeps
        a poll from re-reading the whole conversation's trace payloads, which
        grow with every turn ever taken on the note.

        ``phase`` is present on every execution and is ``None`` for terminal
        ones, so a client reads "what is it doing" from one field either way.
        """
        data = self.chat.representation(conversation)
        active = {AgentExecution.Status.PENDING, AgentExecution.Status.RUNNING}
        executions = data["executions"]
        scoped_ids = (
            None
            if activity_scope == ACTIVITY_ALL
            else self._live_activity_ids(executions, active)
        )
        events = conversation_activity_events(conversation, execution_ids=scoped_ids)
        published_answers = {
            message["execution_id"]: message["content"]
            for message in data["messages"]
            if message["execution_id"] is not None
        }
        for execution in executions:
            execution_active = execution["status"] in active
            execution_events = events.get(execution["id"], [])
            if scoped_ids is None or execution["id"] in scoped_ids:
                execution["activity"] = public_activity(
                    execution_events,
                    execution_active=execution_active,
                    # The final text is dropped only while the chat truly
                    # carries it. Publication is success-gated, so any other
                    # terminal status keeps the text here, and a succeeded run
                    # stuck on publication repair
                    # (``assistant_message_pending``) keeps it too until the
                    # repair lands. A superseded run reports not pending, so an
                    # answer a regeneration replaced stays out.
                    answer_published=(
                        execution["status"] == AgentExecution.Status.SUCCEEDED
                        and not execution["assistant_message_pending"]
                    ),
                    # The published text itself, so the presenter can tell the
                    # answer's own trace row from older narration a lost final
                    # trace write left misflagged as the answer.
                    published_answer=published_answers.get(execution["id"]),
                )
            execution["phase"] = execution_phase(
                execution_events,
                execution_active=execution_active,
                # A pending turn is waiting for a worker to claim it; only a
                # claimed one has model work for the phase to describe.
                execution_claimed=(
                    execution["status"] == AgentExecution.Status.RUNNING
                ),
            )
        return data

    @staticmethod
    def _live_activity_ids(executions: list[dict], active: set) -> list[int]:
        """Executions whose activity a poll may not yet hold settled."""
        now = timezone.now()
        ids = set()
        for execution in executions:
            if execution["status"] in active:
                ids.add(execution["id"])
                continue
            # A terminal turn stays in scope for a grace period after it
            # settles. Excluding it the moment it stops being newest would
            # strand any client that did not poll in between -- its cached
            # feed would show the turn mid-flight forever. A missing
            # timestamp cannot prove the client saw the settled feed, so it
            # counts as fresh; that costs a walk of one turn's rows, never
            # correctness.
            settled_at = execution["finished_at"] or execution["last_activity_at"]
            if settled_at is None or now - settled_at <= ACTIVITY_SETTLED_GRACE:
                ids.add(execution["id"])
        if executions:
            # Ordered by attempt, so the last entry is the newest turn. Its feed
            # is what the client is watching, and on the poll that catches it
            # finishing this is the only chance to hand over the settled version.
            ids.add(executions[-1]["id"])
        return sorted(ids)

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
            pending=True,
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
        transaction.on_commit(lambda: self._schedule_turn(execution.id))
        return execution

    def cancel_active_turn(self, note: Note, user) -> AgentExecution | None:
        """Stop the conversation's in-flight turn; ``None`` if none was running.

        Cancellation is cooperative: the worker is not interrupted here, it
        notices at its next durable write and unwinds. So this returns as soon
        as the intent is recorded, and the turn's status is ``CANCELLED`` from
        that moment even though a model call may still be in flight. Nothing
        the worker does afterwards can revive the row -- every terminal
        transition in the recorder is guarded on ``RUNNING``.
        """
        conversation = self.get_conversation(note, user)
        if conversation is None:
            return None
        execution = (
            conversation.executions.filter(
                status__in=[
                    AgentExecution.Status.PENDING,
                    AgentExecution.Status.RUNNING,
                ]
            )
            .order_by("-attempt")
            .first()
        )
        if execution is None:
            return None
        return execution if self.cancels.cancel(execution) else None

    def _schedule_turn(self, execution_id: int) -> None:
        """Queue the worker turn, failing the execution if the broker refuses.

        A ``PENDING`` row with no task behind it would hold the
        conversation's busy check forever; claiming and failing it instead
        lets the user simply send their message again.
        """
        # Imported here, not at module top: ``tasks`` imports this service, so
        # a top-level import would be a cycle.
        from research_ai.tasks import run_notebook_chat_turn_task

        try:
            run_notebook_chat_turn_task.delay(execution_id)
        except Exception as exc:  # noqa: BLE001 - any enqueue failure
            logger.exception("could not queue notebook chat turn %s", execution_id)
            execution = AgentExecution.objects.filter(id=execution_id).first()
            recorder = (
                self.chat.executions.claim_pending(execution)
                if execution is not None
                else None
            )
            if recorder is not None:
                recorder.on_run_failed(exc)

    # -- worker path ------------------------------------------------------

    def run_turn(self, execution_id: int) -> dict:
        """Drive one prepared execution to a terminal state.

        Everything the turn needs is rebuilt from the execution row, so the
        worker shares no in-memory state with the request that prepared it.
        Idempotent on redelivery: only the delivery that claims the
        ``PENDING`` row runs it; every other delivery is skipped.
        """
        execution = AgentExecution.objects.select_related(
            "conversation", "conversation__user", "trigger_message"
        ).get(id=execution_id)
        recorder = self.chat.executions.claim_pending(
            execution,
            initial_prompt_provenance=AgentExecutionMessage.Provenance.HUMAN,
        )
        if recorder is None:
            logger.info(
                "notebook chat turn %s skipped: status is %s",
                execution_id,
                execution.status,
            )
            return {"execution_id": execution.id, "skipped": True}
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
            execution.model or None,
            native_tools=frozenset({"web_search"}),
        )
        toolset = compose_notebook_toolset(
            note_toolset=NoteToolset(user=conversation.user, note_ids={note.id}),
            openalex_toolset=OpenAlexToolset(client=self._oa_client or OpenAlex()),
            web_search_toolset=NotebookWebSearchToolset(client=self._web_search_client),
            native_tool_names=provider.native_tool_names,
        )
        config = self._turn_config(execution)
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

    def _turn_config(self, execution: AgentExecution) -> NotebookChatConfig:
        """The knobs this turn was submitted with, not today's settings.

        A settings change while the turn sat queued must not make the
        execution's recorded configuration lie about the run; current
        settings only fill keys the stored snapshot lacks.
        """
        stored = execution.configuration or {}
        defaults = self.config
        # Built field-by-field rather than via dataclasses.replace so the
        # value is statically a NotebookChatConfig, not a bare dataclass.
        return NotebookChatConfig(
            **{
                field: (
                    stored[field]
                    if stored.get(field) is not None
                    else getattr(defaults, field)
                )
                for field in ("max_iterations", "max_tokens", "temperature")
            },
            max_message_chars=defaults.max_message_chars,
        )

    def _note_for(self, conversation: AgentConversation) -> Note | None:
        link = conversation.note_links.select_related("note").order_by("id").first()
        return link.note if link else None
