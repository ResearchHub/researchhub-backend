"""Drive an eval case through the production chat engine.

Each run seeds a fresh staff user (the privileged tier, so any catalog model
is selectable and budgets do not interfere) and, for a notebook case, a note
written the way the agent's own tools write one. It then submits the case's
turns one at a time through ``NotebookChatService`` -- or
``AssistantChatService`` over it -- and runs each turn in-process with
``run_turn``, the same call the Celery task makes. Everything the scorers see
is read back from the rows the turn persisted: the trace, the reply, the
usage events, and the notes the conversation is linked to.

Writes are committed, not rolled back: the turn's reservation heartbeat runs
on its own thread and connection, so it could not see an uncommitted
execution. Run against a throwaway database.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db.models import Sum

from note.related_models.note_model import Note
from note.services.note_content_service import NoteContentService
from note.services.note_creation_service import NoteCreationService
from research_ai.evals.cases import ASSISTANT, EvalCase, NoteFixture
from research_ai.models import AgentConversation, AgentExecution, LLMUsageEvent
from research_ai.services.assistant_chat.service import AssistantChatService
from research_ai.services.notebook_chat.service import (
    ASSISTANT_WORKFLOW,
    NotebookChatService,
)
from research_ai.services.notebook_chat.service import WORKFLOW as NOTEBOOK_WORKFLOW
from utils.prosemirror import (
    BLOCK_EDITOR,
    EDITOR_ID_ATTRS,
    compact_blocks,
    parse_blocks,
)

logger = logging.getLogger(__name__)

EVAL_EMAIL_DOMAIN = "agent-evals.researchhub.test"


@dataclass
class ToolCall:
    turn: int
    name: str
    input: dict
    # The result content as JSON text.
    result: str
    is_error: bool
    # Run by the provider inside the turn (its own web_search), not by us.
    native: bool = False


@dataclass
class TurnRun:
    index: int
    message: str
    execution_id: int
    status: str
    error: str
    reply: str
    iterations: int
    input_tokens: int
    output_tokens: int
    cost_microusd: int
    duration_ms: int | None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class NoteSnapshot:
    id: int
    title: str
    document_type: str
    blocks: list
    plain_text: str


@dataclass
class CaseRun:
    case_id: str
    agent: str
    model: str
    trial: int
    turns: list[TurnRun] = field(default_factory=list)
    notes_before: dict[int, NoteSnapshot] = field(default_factory=dict)
    notes_after: dict[int, NoteSnapshot] = field(default_factory=dict)
    user_id: int | None = None
    conversation_id: int | None = None
    # A failure outside any turn (fixture, submit); turn failures stay on
    # their turn.
    error: str = ""
    elapsed_s: float = 0.0

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [call for turn in self.turns for call in turn.tool_calls]


class _AllowAllScreening:
    """Lets every message through: evals grade the agent, not the screen."""

    def rejects(self, *_args, **_kwargs) -> bool:
        return False


class EvalChatService(NotebookChatService):
    """The production engine without the Celery hand-off.

    ``submit_message`` schedules the worker task on commit; the harness runs
    each turn itself right after submitting it, so nothing is queued that a
    stack's worker could race it for.
    """

    def _schedule_turn(self, execution_id: int) -> None:
        # Deliberately empty: AgentEvalHarness calls run_turn itself.
        pass


def build_engine(workflow: str, **overrides) -> NotebookChatService:
    """The eval engine for ``workflow``; ``overrides`` replace collaborators."""
    overrides.setdefault("screening_service", _AllowAllScreening())
    return EvalChatService(workflow=workflow, **overrides)


class AgentEvalHarness:
    """Runs cases against one model.

    ``model_ref`` is a catalog ref (``provider:model``), or ``None`` for the
    tier default. ``engine_factory`` builds the engine for a workflow and is
    injectable for tests.
    """

    def __init__(
        self,
        *,
        model_ref: str | None = None,
        engine_factory: Callable[[str], NotebookChatService] | None = None,
    ):
        self.model_ref = model_ref
        self._engine_factory = (
            build_engine if engine_factory is None else engine_factory
        )

    def run(self, case: EvalCase, *, trial: int = 0) -> CaseRun:
        run = CaseRun(
            case_id=case.id,
            agent=case.agent,
            model=self.model_ref or "",
            trial=trial,
        )
        started = time.monotonic()
        try:
            self._run(case, run)
        except Exception as exc:  # noqa: BLE001 - one bad case must not end the suite
            logger.exception("eval case %s (trial %s) crashed", case.id, trial)
            run.error = f"{type(exc).__name__}: {exc}"
        run.elapsed_s = round(time.monotonic() - started, 2)
        return run

    def _run(self, case: EvalCase, run: CaseRun) -> None:
        user = _create_user()
        run.user_id = user.id
        if case.agent == ASSISTANT:
            chat = AssistantChatService(engine=self._engine_factory(ASSISTANT_WORKFLOW))
            engine = chat.engine
            conversation = chat.create_conversation(user)

            def submit(text):
                return chat.submit_message(conversation, text, model_ref=self.model_ref)

        else:
            engine = self._engine_factory(NOTEBOOK_WORKFLOW)
            note = _create_note(user, case.note)
            run.notes_before[note.id] = snapshot_note(note)
            conversation = engine.create_conversation(note, user)

            def submit(text):
                return engine.submit_message(
                    note, conversation, text, model_ref=self.model_ref
                )

        run.conversation_id = conversation.id
        for index, text in enumerate(case.turns):
            execution = submit(text)
            if not run.model:
                run.model = execution.model
            engine.run_turn(execution.id)
            run.turns.append(collect_turn(index, text, execution))
        for note in _linked_notes(conversation):
            run.notes_after[note.id] = snapshot_note(note)


def _create_user():
    email = f"eval-{uuid.uuid4().hex[:12]}@{EVAL_EMAIL_DOMAIN}"
    return get_user_model().objects.create_user(
        username=email, email=email, password=None, is_staff=True
    )


def _create_note(user, fixture: NoteFixture) -> Note:
    note = NoteCreationService().create_private_note(
        created_by=user, title=fixture.title, document_type=fixture.document_type
    )
    NoteContentService().create_version(
        note,
        {"type": "doc", "content": parse_blocks(BLOCK_EDITOR, fixture.blocks)},
        created_by=user,
    )
    return note


def _linked_notes(conversation: AgentConversation) -> list[Note]:
    return [
        link.note
        for link in conversation.note_links.select_related("note").order_by("id")
    ]


def snapshot_note(note: Note) -> NoteSnapshot:
    note.refresh_from_db()
    version = note.latest_version
    doc = json.loads(version.json) if version and version.json else None
    return NoteSnapshot(
        id=note.id,
        title=note.title,
        document_type=note.document_type,
        blocks=(
            compact_blocks(BLOCK_EDITOR, doc, omit_attrs=EDITOR_ID_ATTRS) if doc else []
        ),
        plain_text=version.plain_text if version else "",
    )


def collect_turn(index: int, text: str, execution: AgentExecution) -> TurnRun:
    execution.refresh_from_db()
    reply = getattr(execution, "generated_chat_message", None)
    turn = TurnRun(
        index=index,
        message=text,
        execution_id=execution.id,
        status=execution.status,
        error=execution.error_message,
        reply=reply.content if reply is not None else "",
        iterations=execution.iterations or 0,
        input_tokens=execution.input_tokens or 0,
        output_tokens=execution.output_tokens or 0,
        cost_microusd=LLMUsageEvent.objects.filter(execution=execution).aggregate(
            total=Sum("cost_microusd")
        )["total"]
        or 0,
        duration_ms=execution.duration_ms,
    )
    calls = {}
    for message in execution.messages.order_by("execution_sequence"):
        for block in message.content or []:
            _collect_block(turn, calls, block)
    return turn


def _collect_block(turn: TurnRun, calls: dict[str, ToolCall], block: dict) -> None:
    """Fold one trace block into ``turn``, pairing results with their calls."""
    kind = block.get("type")
    if kind == "tool_use":
        calls[block["id"]] = ToolCall(
            turn=turn.index,
            name=block["name"],
            input=block.get("input") or {},
            result="",
            is_error=False,
        )
        turn.tool_calls.append(calls[block["id"]])
    elif kind == "tool_result" and block.get("tool_use_id") in calls:
        call = calls[block["tool_use_id"]]
        call.result = json.dumps(block.get("content"), default=str)
        call.is_error = bool(block.get("is_error"))
    elif kind == "server_tool" and isinstance(block.get("data"), dict):
        _collect_server_tool(turn, calls, block["data"])


def _collect_server_tool(turn: TurnRun, calls: dict[str, ToolCall], data: dict):
    """A provider-run tool: its ``server_tool_use`` request becomes a native
    ``ToolCall``, and the ``*_result`` block that answers it fills its result.
    The request's input never counts as a result."""
    block_type = str(data.get("type", ""))
    if block_type == "server_tool_use" and data.get("id"):
        calls[data["id"]] = ToolCall(
            turn=turn.index,
            name=str(data.get("name", "")),
            input=data.get("input") or {},
            result="",
            is_error=False,
            native=True,
        )
        turn.tool_calls.append(calls[data["id"]])
    elif block_type.endswith("_result") and data.get("tool_use_id") in calls:
        call = calls[data["tool_use_id"]]
        content = data.get("content")
        call.result = json.dumps(content, default=str)
        # e.g. web_search_tool_result_error in place of the result list.
        call.is_error = isinstance(content, dict) and str(
            content.get("type", "")
        ).endswith("_error")
