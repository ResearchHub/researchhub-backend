"""Rule-based scorers over a ``CaseRun``.

Each scorer takes the case and its run and returns a ``Score`` in [0, 1], or
``None`` when the check does not apply to the case. They read only what the
harness collected, so they are deterministic and cheap to re-run on a saved
report. A run that crashed outside its turns scores 0 on ``turn_ok`` and is
not applicable everywhere else: there is nothing to grade.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from research_ai.evals.cases import EvalCase
from research_ai.evals.harness import CaseRun, NoteSnapshot
from research_ai.models import AgentExecution
from research_ai.services.note_tools import (
    CREATE_NOTE,
    EDIT_NOTE,
    READ_NOTE,
    RENAME_NOTE,
)
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)


@dataclass
class Score:
    name: str
    value: float
    details: list[str] = field(default_factory=list)


Scorer = Callable[[EvalCase, CaseRun], Score | None]

_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>\]\)]+", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[[^\]\n]+\]\(\s*https?://[^)\s]+\s*\)")
_BARE_URL = re.compile(r"https?://\S+")
# proposal_writing.txt: what belongs in the reply, never in the note.
_PROPOSAL_TELLS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"remains? to be (confirmed|determined|set|decided|finali[sz]ed)",
        r"\bto be determined\b|\bTBD\b",
        r"before submission",
        r"no institutional commitment",
        r"not (yet )?a finali[sz]ed",
        r"planning ceiling",
        r"no sample size is claimed",
        r"\[(insert|placeholder|todo)\b",
    )
]
# A block of the note this long, repeated verbatim in a reply, counts as the
# note being pasted back.
_PASTE_MIN_CHARS = 120
_PASTE_MAX_BLOCKS = 2
_NOTE_TOOLS = frozenset({READ_NOTE, EDIT_NOTE, CREATE_NOTE, RENAME_NOTE})


def turn_ok(case: EvalCase, run: CaseRun) -> Score:
    details = [run.error] if run.error else []
    details += [
        f"turn {turn.index}: {turn.status} {turn.error}".strip()
        for turn in run.turns
        if turn.status != AgentExecution.Status.SUCCEEDED
    ]
    ok = not details and len(run.turns) == len(case.turns)
    return Score("turn_ok", 1.0 if ok else 0.0, details)


def tool_expectations(case: EvalCase, run: CaseRun) -> Score | None:
    """Required and forbidden tools, and no edit of a note never read."""
    if run.error:
        return None
    called = {call.name for call in run.tool_calls}
    # A required tool counts only once it worked: a failed edit_note followed
    # by a cheerful reply has not done the edit.
    succeeded = {call.name for call in run.tool_calls if not call.is_error}
    details = [
        f"never called {name}" if name not in called else f"every {name} call failed"
        for name in case.expect.tools_called
        if name not in succeeded
    ]
    details += [
        f"called {name}" for name in case.expect.tools_not_called if name in called
    ]
    # Editing rule 1: edit from a read. Notes the agent created this run
    # start empty and are exempt.
    read = set()
    for call in run.tool_calls:
        note_id = _note_id(call.input.get("note_id"))
        if call.name == READ_NOTE:
            read.add(note_id)
        elif (
            call.name == EDIT_NOTE
            and note_id in run.notes_before
            and note_id not in read
        ):
            details.append(f"edit_note on note {note_id} before reading it")
    checks = len(case.expect.tools_called) + len(case.expect.tools_not_called) + 1
    return Score("tool_expectations", _fraction(checks, len(details)), details)


def edit_scope(case: EvalCase, run: CaseRun) -> Score | None:
    """Sections the case says to leave alone come out unchanged."""
    if run.error or not run.notes_before:
        return None
    if not case.expect.unchanged_sections and not case.expect.note_unchanged:
        return None
    details = []
    checks = 0
    for note_id, before in run.notes_before.items():
        after = run.notes_after.get(note_id)
        if after is None:
            details.append(f"note {note_id} missing after the run")
            continue
        note_checks, note_details = _edit_scope_of(case, before, after)
        checks += note_checks
        details += note_details
    return Score("edit_scope", _fraction(max(checks, 1), len(details)), details)


def _edit_scope_of(
    case: EvalCase, before: NoteSnapshot, after: NoteSnapshot
) -> tuple[int, list[str]]:
    """(checks run, failures) for one note the run started with."""
    checks = len(case.expect.unchanged_sections)
    details = []
    if case.expect.note_unchanged:
        checks += 1
        if after.blocks != before.blocks:
            details.append(f"note {before.id} changed")
    before_sections = sections(before.blocks)
    after_sections = sections(after.blocks)
    for heading in case.expect.unchanged_sections:
        if heading not in before_sections:
            details.append(f"fixture has no section {heading!r}")
        elif after_sections.get(heading) != before_sections[heading]:
            details.append(f"section {heading!r} changed")
    return checks, details


def grounded_citations(case: EvalCase, run: CaseRun) -> Score | None:
    """Every DOI the run added to a note or reply came from somewhere.

    A DOI is grounded when the user, the fixture note, or an external tool
    result in this run carried it. Note tool results are not evidence: they
    echo back what the agent itself wrote. Not applicable when the run cites
    no new DOI.
    """
    if run.error:
        return None
    sources = " ".join(
        [*case.turns]
        + [
            note.plain_text + json.dumps(note.blocks)
            for note in run.notes_before.values()
        ]
        + [
            call.result
            for call in run.tool_calls
            if call.name not in _NOTE_TOOLS and not call.is_error
        ]
        + [result for turn in run.turns for result in turn.server_tool_results]
    ).lower()
    cited = set()
    for note in run.notes_after.values():
        cited |= _dois(json.dumps(note.blocks))
    for turn in run.turns:
        cited |= _dois(turn.reply)
    if not cited:
        return None
    details = [f"ungrounded DOI {doi}" for doi in sorted(cited) if doi not in sources]
    return Score("grounded_citations", _fraction(len(cited), len(details)), details)


def link_format(case: EvalCase, run: CaseRun) -> Score | None:
    """URLs the run wrote into a note are link marks, not plain text."""
    if run.error or not run.notes_after:
        return None
    details = []
    for note_id, after in run.notes_after.items():
        before = run.notes_before.get(note_id)
        known = set(_unlinked_urls(before.blocks)) if before else set()
        details += [
            f"note {note_id}: {problem}"
            for problem in _unlinked_urls(after.blocks)
            if problem not in known
        ]
    return Score("link_format", 0.0 if details else 1.0, details)


def proposal_hygiene(case: EvalCase, run: CaseRun) -> Score | None:
    """No disclaimers, deferrals, or applicant checklists in a proposal note."""
    if run.error:
        return None
    notes = [
        note
        for note in run.notes_after.values()
        if case.expect.proposal_hygiene
        or note.document_type in (PREREGISTRATION, GRANT)
    ]
    if not notes:
        return None
    details = []
    for note in notes:
        before = run.notes_before.get(note.id)
        old_text = (before.plain_text if before else "").lower()
        details += [
            f"note {note.id}: {_excerpt(note.plain_text, match)}"
            for pattern in _PROPOSAL_TELLS
            for match in pattern.finditer(note.plain_text)
            if match.group(0).lower() not in old_text
        ]
    return Score("proposal_hygiene", 0.0 if details else 1.0, details)


def reply_shape(case: EvalCase, run: CaseRun) -> Score | None:
    """Each turn ends in a short reply that does not paste the note back."""
    if run.error or not run.turns:
        return None
    details = []
    blocks = [
        text
        for note in run.notes_after.values()
        for text in note.plain_text.split("\n")
        if len(text) >= _PASTE_MIN_CHARS
    ]
    for turn in run.turns:
        if not turn.reply.strip():
            details.append(f"turn {turn.index}: no reply")
            continue
        if len(turn.reply) > case.expect.max_reply_chars:
            details.append(
                f"turn {turn.index}: reply is {len(turn.reply)} chars "
                f"(max {case.expect.max_reply_chars})"
            )
        pasted = sum(1 for text in blocks if text in turn.reply)
        if pasted > _PASTE_MAX_BLOCKS:
            details.append(f"turn {turn.index}: pastes {pasted} note paragraphs")
    return Score("reply_shape", _fraction(len(run.turns), len(details)), details)


SCORERS: list[Scorer] = [
    turn_ok,
    tool_expectations,
    edit_scope,
    grounded_citations,
    link_format,
    proposal_hygiene,
    reply_shape,
]


def score_run(case: EvalCase, run: CaseRun) -> list[Score]:
    return [score for scorer in SCORERS if (score := scorer(case, run)) is not None]


def sections(blocks: list) -> dict[str, list]:
    """Heading text -> the blocks under it, down to the next heading at the
    same or a higher level. Blocks before the first heading are ``""``."""
    result: dict[str, list] = {"": []}
    open_sections: list[tuple[int, str]] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "heading":
            level = (block.get("attrs") or {}).get("level", 1)
            while open_sections and open_sections[-1][0] >= level:
                open_sections.pop()
            # A subsection's heading is part of every section around it.
            for _level, heading in open_sections:
                result[heading].append(block)
            heading = _text(block)
            open_sections.append((level, heading))
            result.setdefault(heading, [])
            continue
        for _level, heading in open_sections or [(0, "")]:
            result[heading].append(block)
    return result


def _unlinked_urls(blocks: list) -> list[str]:
    problems = []
    for text, linked in _text_runs(blocks):
        problems += [
            f"markdown link {match.group(0)}" for match in _MARKDOWN_LINK.finditer(text)
        ]
        if not linked:
            stripped = _MARKDOWN_LINK.sub("", text)
            problems += [f"bare URL {url}" for url in _BARE_URL.findall(stripped)]
    return problems


def _text_runs(node, linked: bool = False):
    """(text, has a link mark) for every text run in compact ``node``."""
    if isinstance(node, str):
        yield node, linked
    elif isinstance(node, list):
        for child in node:
            yield from _text_runs(child, linked)
    elif isinstance(node, dict):
        if node.get("type") == "text":
            marks = node.get("marks") or []
            has_link = any(mark.get("type") == "link" for mark in marks)
            yield node.get("text", ""), linked or has_link
        else:
            yield from _text_runs(node.get("content") or [], linked)


def _text(node) -> str:
    return "".join(text for text, _linked in _text_runs(node))


def _dois(text: str) -> set[str]:
    return {match.rstrip(".,;:").lower() for match in _DOI.findall(text or "")}


def _excerpt(text: str, match: re.Match, width: int = 40) -> str:
    start = max(match.start() - width, 0)
    return "..." + text[start : match.end() + width].replace("\n", " ") + "..."


def _fraction(checks: int, failures: int) -> float:
    return round(max(checks - failures, 0) / checks, 3) if checks else 1.0


def _note_id(value) -> int | None:
    try:
        return int(value)
    except TypeError, ValueError:
        return None
