"""The notebook chat assistant: research + note edits driven by user feedback.

A user can keep any number of chats on a note, workflow ``notebook_chat``.
Each chat is its own ``AgentConversation`` -- resolved by id, never by
position -- with its own context lineage and its own busy check, so turns in
different chats on the same note may run concurrently. That is safe by
construction: note edits are optimistic-concurrency guarded and versioned
(see ``NoteToolset``), so parallel agents can at worst reject each other's
stale writes, never corrupt the note. A turn is split across two processes:

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
from django.db.models import Exists, OuterRef, Subquery
from django.db.models.functions import Left
from django.utils import timezone

from note.related_models.note_model import Note
from research_ai.models import (
    AgentConversation,
    AgentConversationMessage,
    AgentExecution,
)
from research_ai.models.agent import AgentExecutionMessage
from research_ai.prompts.notebook_chat_prompts import build_notebook_chat_system_prompt
from research_ai.services.agent import (
    AgentRunError,
    AgentService,
    generator_model_ref,
    resolve_provider,
    split_model_ref,
    validate_model_ref,
)
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
from research_ai.services.notebook_chat.events import (
    TURN_CANCELLED,
    TURN_QUEUED,
    ConversationEventPublisher,
    PublishingRecorder,
)
from research_ai.services.notebook_chat.grant_tools import (
    GrantSearchToolset,
    SelectedRFPToolset,
)
from research_ai.services.notebook_chat.streaming import ExecutionStreamStore
from research_ai.services.notebook_chat.toolset import (
    NotebookWebSearchToolset,
    compose_notebook_toolset,
)
from research_ai.services.researcher_profile.openalex_tools import OpenAlexToolset
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

WORKFLOW = "notebook_chat"

# Activity projection scopes for ``NotebookChatService.representation``.
ACTIVITY_ALL = "all"
ACTIVITY_LIVE = "live"

# How long a turn stays in the live projection after its last transition. A
# turn can settle and be displaced as newest by a fresh message between two
# polls -- cancel, then rephrase -- and the settled feed must still reach a
# client whose cached copy shows the turn mid-flight. A stuck answer that
# finally publishes restarts the clock the same way: publication stamps the
# turn's heartbeat, so the re-rendered feed reaches every client regardless of
# which request landed it. The window needs only to outlast a polling
# interval; a client that stopped polling for longer is expected to refetch the
# full projection anyway. It also keeps a just-cancelled turn in scope while
# its worker unwinds, when trace rows can genuinely still land.
ACTIVITY_SETTLED_GRACE = timedelta(seconds=60)

# Derived chat titles are list labels, not documents: one collapsed line,
# well under the model field's 255-char bound.
TITLE_MAX_CHARS = 120

# How much of a chat's newest message the listing carries as a preview,
# truncated in the database so a 20k-character turn never rides along.
LIST_PREVIEW_CHARS = 160


def _derive_title(text: str) -> str:
    """A list-friendly chat name from the first message: one bounded line."""
    return " ".join(text.split())[:TITLE_MAX_CHARS].rstrip()


class NotebookChatService:
    """Prepare and run notebook chat turns.

    Runtime collaborators are injectable for tests; in production they default
    to the settings-configured generator provider, OpenAlex client, Brave web
    search, database persistence services, and the channel-layer event
    publisher (see ``events``) that nudges subscribed WebSocket clients as a
    turn advances.
    """

    def __init__(
        self,
        *,
        provider=None,
        oa_client: OpenAlex | None = None,
        web_search_client=None,
        grant_toolset_factory=None,
        chat_service: AgentChatService | None = None,
        conversation_service: AgentConversationService | None = None,
        note_conversation_service: NoteAgentConversationService | None = None,
        context_service: AgentContextService | None = None,
        cancel_service: AgentExecutionCancelService | None = None,
        config: NotebookChatConfig | None = None,
        event_publisher: ConversationEventPublisher | None = None,
        stream_store: ExecutionStreamStore | None = None,
    ):
        self._provider = provider
        self._oa_client = oa_client
        self._web_search_client = web_search_client
        self._grant_toolset_factory = (
            GrantSearchToolset
            if grant_toolset_factory is None
            else grant_toolset_factory
        )
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
        self.events = (
            ConversationEventPublisher() if event_publisher is None else event_publisher
        )
        self.streams = ExecutionStreamStore() if stream_store is None else stream_store
        self._config = config

    @property
    def config(self) -> NotebookChatConfig:
        return self._config or NotebookChatConfig.from_settings()

    # -- request path -----------------------------------------------------

    def get_conversation(
        self, note: Note, user, conversation_id: int
    ) -> AgentConversation | None:
        """The user's notebook chat ``conversation_id`` on ``note``, if any.

        Scoped to the note, the requesting user, and this workflow, so a
        conversation id belonging to another user, another note, or another
        workflow does not resolve -- the API turns that ``None`` into a 404.
        """
        return (
            self.note_conversations.for_note(note)
            .filter(workflow=WORKFLOW, user=user, id=conversation_id)
            .first()
        )

    def list_conversations(self, note: Note, user) -> list[dict]:
        """The user's chats on ``note``, newest activity first.

        A listing projection, deliberately not ``representation``: one query
        with a bounded preview of each chat's newest message, instead of
        walking every conversation's executions and running publication
        repair. ``has_active_turn`` is what lets a chat picker show a spinner
        without fetching any chat's full state.
        """
        last_message = (
            AgentConversationMessage.objects.filter(
                conversation=OuterRef("pk"), is_active=True
            )
            .order_by("-sequence")
            .annotate(preview=Left("content", LIST_PREVIEW_CHARS))
            .values("preview")[:1]
        )
        conversations = (
            self.note_conversations.for_note(note)
            .filter(workflow=WORKFLOW, user=user)
            .annotate(
                last_message_preview=Subquery(last_message),
                has_active_turn=Exists(
                    AgentExecution.objects.filter(
                        conversation=OuterRef("pk"),
                        status__in=[
                            AgentExecution.Status.PENDING,
                            AgentExecution.Status.RUNNING,
                        ],
                    )
                ),
            )
        )
        return [
            {
                "id": conversation.id,
                "title": conversation.title,
                "created_date": conversation.created_date,
                "updated_date": conversation.updated_date,
                "last_message_preview": conversation.last_message_preview,
                "has_active_turn": conversation.has_active_turn,
            }
            for conversation in conversations
        ]

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
        settled -- active turns, anything whose last transition happened
        within ``ACTIVITY_SETTLED_GRACE`` (settling, or a stuck answer
        publishing late: either re-renders the feed, and the turn can be
        displaced by a new message before the client's next poll), and the
        latest attempt. The rest **omit the ``activity`` key entirely**. An
        absent key means "unchanged, keep what you have"; it is deliberately
        not an empty list, which would be indistinguishable from a turn that
        used no tools. This is what keeps a poll from re-reading the whole
        conversation's trace payloads, which grow with every turn ever taken
        on the note.

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
            stream = None
            if execution_active:
                # Present even when empty so reconnecting clients can replace
                # a stale transient preview with the current snapshot.
                stream = self._stream_snapshot(execution["id"])
                execution["stream"] = stream
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
            # A live provider delta is newer than the last durable trace row.
            # It can therefore refine the coarse phase without becoming
            # durable state itself.
            if stream and stream.get("items"):
                last_item = stream["items"][-1]
                if last_item.get("type") == "narration":
                    execution["phase"] = {
                        "state": "responding",
                        "label": "Writing a response",
                    }
                elif last_item.get("type") == "thinking":
                    execution["phase"] = {
                        "state": "thinking",
                        "label": "Thinking",
                    }
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
            # A terminal turn stays in scope for a grace period after its
            # last transition -- the *latest* of finishing and the final
            # heartbeat, because a stuck answer that publishes late stamps
            # ``last_activity_at`` and re-renders the turn no matter how long
            # ago it finished, and no request but the one that happened to
            # land it would otherwise know. Excluding a turn the moment it
            # stops being newest would likewise strand any client that did
            # not poll in between -- its cached feed would show the turn
            # mid-flight forever. A missing timestamp cannot prove the client
            # saw the settled feed, so it counts as fresh; that costs a walk
            # of one turn's rows, never correctness.
            transitions = [
                at
                for at in (execution["finished_at"], execution["last_activity_at"])
                if at is not None
            ]
            if not transitions or now - max(transitions) <= ACTIVITY_SETTLED_GRACE:
                ids.add(execution["id"])
        if executions:
            # Ordered by attempt, so the last entry is the newest turn. Its feed
            # is what the client is watching, and on the poll that catches it
            # finishing this is the only chance to hand over the settled version.
            ids.add(executions[-1]["id"])
        return sorted(ids)

    def create_conversation(
        self, note: Note, user, title: str = ""
    ) -> AgentConversation:
        """Create a new chat on ``note`` owned by ``user``.

        Any number of chats per (note, user) is expected, so concurrent
        creates are simply two new chats -- no serialization needed. Atomic so
        a conversation never outlives a failed note attachment.
        """
        with transaction.atomic():
            conversation = self.conversations.create(
                user=user, workflow=WORKFLOW, title=title
            )
            self.note_conversations.attach(conversation, note)
        return conversation

    def rename_conversation(
        self, conversation: AgentConversation, title: str
    ) -> AgentConversation:
        self.conversations.set_title(conversation, title)
        return conversation

    def submit_message(
        self,
        note: Note,
        conversation: AgentConversation,
        text: str,
        *,
        model_ref: str | None = None,
    ) -> AgentExecution:
        """Record the user's message on ``conversation`` and schedule the turn.

        ``conversation`` must have been resolved through ``get_conversation``
        so it is known to belong to ``note``. A chat still untitled takes its
        name from this message. ``model_ref`` selects the model for the first
        turn. Later turns reuse that model; requesting a different provider or
        model raises ``ValueError``.
        Raises ``ValueError`` on an empty or oversized message or a model not
        in the selectable catalog, and lets ``AgentConversationBusyError``
        propagate when a turn is already running on this conversation (the
        API maps it to a 409); other chats on the note are unaffected.
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("message must not be empty")
        config = self.config
        if len(text) > config.max_message_chars:
            raise ValueError(f"message exceeds {config.max_message_chars} characters")
        # Validated here, not only at the API boundary, so an execution can
        # never be prepared against a model the catalog does not offer. The
        # first execution pins the conversation's model; subsequent turns
        # inherit that snapshot even if the configured default or catalog
        # changes, and an explicit attempt to switch is rejected.
        selected_model = validate_model_ref(model_ref)
        with transaction.atomic():
            # Keep model resolution in the same conversation lock as turn
            # preparation. Two first-message requests with different models
            # must not both observe an unpinned conversation.
            locked_conversation = AgentConversation.objects.select_for_update().get(
                id=conversation.id
            )
            conversation_model = (
                locked_conversation.executions.exclude(model="")
                .order_by("attempt")
                .values_list("model", flat=True)
                .first()
            )
            if (
                conversation_model is not None
                and selected_model is not None
                and selected_model != conversation_model
            ):
                raise ValueError(
                    "model cannot be changed after a conversation has started"
                )
            model = conversation_model or selected_model or generator_model_ref()

            prepared = self.chat.prepare_turn(
                locked_conversation,
                text,
                pending=True,
                provider=split_model_ref(model)[0],
                model=model,
                configuration={
                    "max_iterations": config.max_iterations,
                    "max_tokens": config.max_tokens,
                    "temperature": config.temperature,
                    "note_id": note.id,
                },
                system_prompt=build_notebook_chat_system_prompt(note),
            )
        execution = prepared.execution
        # After prepare_turn so a refused turn (busy, for instance) names
        # nothing; the filtered update keeps a concurrent rename authoritative.
        self.conversations.set_title_if_blank(conversation, _derive_title(text))
        # Publish before scheduling: under autocommit both run immediately in
        # this order, keeping turn_queued ahead of anything the worker or a
        # synchronous broker refusal publishes.
        self.events.publish(conversation.id, execution.id, TURN_QUEUED)
        transaction.on_commit(lambda: self._schedule_turn(execution.id))
        return execution

    def cancel_active_turn(
        self, conversation: AgentConversation
    ) -> AgentExecution | None:
        """Stop the conversation's in-flight turn; ``None`` if none was running.

        Cancellation is cooperative: the worker is not interrupted here, it
        notices at its next durable write and unwinds. The turn's status is
        ``CANCELLED`` immediately even though a model call may still be in
        flight. Nothing the worker does afterwards can revive the row -- every
        terminal transition in the recorder is guarded on ``RUNNING``. Clients
        likewise treat terminal status as authoritative and ignore any
        best-effort preview delta already in flight.
        """
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
        if not self.cancels.cancel(execution):
            return None
        try:
            self.streams.clear(execution.id)
        except Exception:  # noqa: BLE001 - preview cleanup is optional
            logger.warning(
                "notebook chat stream clear failed during cancellation (execution=%s)",
                execution.id,
                exc_info=True,
            )
        # The worker's durable writes stop once the row is terminal. A preview
        # delta already in flight is harmless because clients give this
        # terminal transition precedence for the execution.
        self.events.publish(conversation.id, execution.id, TURN_CANCELLED)
        return execution

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
                self._publishing_recorder(recorder, execution).on_run_failed(exc)

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
        # Every durable write and terminal transition below flows through the
        # recorder, so wrapping it here is what pushes the whole turn's
        # progress to subscribed clients.
        recorder = self._publishing_recorder(recorder, execution)
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
            grant_toolset=self._grant_toolset_factory(user=conversation.user),
            selected_rfp_toolset=(
                SelectedRFPToolset(note=note, user=conversation.user)
                if note.document_type == PREREGISTRATION
                else None
            ),
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

    def _publishing_recorder(
        self, recorder, execution: AgentExecution
    ) -> PublishingRecorder:
        """Wrap ``recorder`` so its writes nudge the chat's WebSocket group."""
        return PublishingRecorder(
            recorder,
            self.events,
            conversation_id=execution.conversation_id,
            execution_id=execution.id,
            stream_store=self.streams,
        )

    def _stream_snapshot(self, execution_id: int) -> dict | None:
        """Read an optional transient preview without breaking durable chat reads."""
        try:
            return self.streams.get(execution_id)
        except Exception:  # noqa: BLE001 - stream recovery is best-effort
            logger.warning(
                "notebook chat stream read failed (execution=%s)",
                execution_id,
                exc_info=True,
            )
            return None

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
        # Presence check, not ``is not None``: a stored null is a recorded
        # choice (max_tokens null = the model's own ceiling), not a gap.
        return NotebookChatConfig(
            **{
                field: (stored[field] if field in stored else getattr(defaults, field))
                for field in ("max_iterations", "max_tokens", "temperature")
            },
            max_message_chars=defaults.max_message_chars,
        )

    def _note_for(self, conversation: AgentConversation) -> Note | None:
        link = conversation.note_links.select_related("note").order_by("id").first()
        return link.note if link else None
