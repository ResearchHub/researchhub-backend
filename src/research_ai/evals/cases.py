"""Eval case files: loading and validation.

A case is one YAML file::

    id: notebook/tighten-methods-only
    agent: notebook              # or: assistant
    note:                        # notebook only
      title: Sleep and memory
      document_type: PREREGISTRATION
      blocks:                    # the compact dialect read_note returns
        - "## Methods"           # harness shorthand: "#".."######" + space
        - "We will recruit participants."
    turns:
      - "Tighten the Methods section. Leave everything else alone."
    expect:
      tools_called: [read_note, edit_note]
      tools_not_called: [create_note]
      unchanged_sections: [Introduction]
      note_unchanged: false
      proposal_hygiene: true

Unknown keys are rejected so a typo in ``expect`` cannot silently disable a
check.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from researchhub_document.related_models.constants.document_type import (
    GRANT,
    NOTE,
    PREREGISTRATION,
)

CASES_DIR = Path(__file__).parent / "cases"

NOTEBOOK = "notebook"
ASSISTANT = "assistant"
AGENTS = (NOTEBOOK, ASSISTANT)
NOTE_TYPES = (NOTE, PREREGISTRATION, GRANT)

_HEADING = re.compile(r"^(#{1,6}) (.+)$")
_CASE_KEYS = {"id", "agent", "note", "turns", "expect"}
_NOTE_KEYS = {"title", "document_type", "blocks"}
_EXPECT_KEYS = {
    "tools_called",
    "tools_not_called",
    "unchanged_sections",
    "note_unchanged",
    "proposal_hygiene",
    "max_reply_chars",
}


class CaseError(ValueError):
    """A case file is malformed; the message names the file."""


@dataclass(frozen=True)
class NoteFixture:
    title: str
    document_type: str
    # Compact blocks, with heading shorthand already expanded.
    blocks: list


@dataclass(frozen=True)
class Expectations:
    tools_called: list[str] = field(default_factory=list)
    tools_not_called: list[str] = field(default_factory=list)
    unchanged_sections: list[str] = field(default_factory=list)
    note_unchanged: bool = False
    proposal_hygiene: bool = False
    max_reply_chars: int = 3000


@dataclass(frozen=True)
class EvalCase:
    id: str
    agent: str
    turns: list[str]
    note: NoteFixture | None = None
    expect: Expectations = field(default_factory=Expectations)


def load_cases(
    root: Path = CASES_DIR, *, agent: str | None = None, pattern: str = "*"
) -> list[EvalCase]:
    """Every case under ``root`` whose id matches ``pattern``, sorted by id."""
    cases = [load_case(path) for path in sorted(root.rglob("*.yaml"))]
    return [
        case
        for case in cases
        if (agent is None or case.agent == agent) and Path(case.id).match(pattern)
    ]


def load_case(path: Path) -> EvalCase:
    try:
        raw = yaml.safe_load(path.read_text())
        return parse_case(raw)
    except (yaml.YAMLError, CaseError) as exc:
        raise CaseError(f"{path}: {exc}") from exc


def parse_case(raw) -> EvalCase:
    if not isinstance(raw, dict):
        raise CaseError("a case must be a mapping")
    _reject_unknown(raw, _CASE_KEYS, "case")
    case_id = raw.get("id")
    if not isinstance(case_id, str) or not case_id:
        raise CaseError("id must be a non-empty string")
    agent = raw.get("agent")
    if agent not in AGENTS:
        raise CaseError(f"agent must be one of {AGENTS}")
    turns = raw.get("turns")
    if (
        not isinstance(turns, list)
        or not turns
        or not all(isinstance(turn, str) and turn.strip() for turn in turns)
    ):
        raise CaseError("turns must be a non-empty list of messages")
    note = _parse_note(raw.get("note"))
    if agent == NOTEBOOK and note is None:
        raise CaseError("a notebook case needs a note")
    if agent == ASSISTANT and note is not None:
        raise CaseError("an assistant case starts with no note")
    return EvalCase(
        id=case_id,
        agent=agent,
        turns=turns,
        note=note,
        expect=_parse_expect(raw.get("expect") or {}),
    )


def _parse_note(raw) -> NoteFixture | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CaseError("note must be a mapping")
    _reject_unknown(raw, _NOTE_KEYS, "note")
    document_type = raw.get("document_type", NOTE)
    if document_type not in NOTE_TYPES:
        raise CaseError(f"note.document_type must be one of {NOTE_TYPES}")
    blocks = raw.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise CaseError("note.blocks must be a non-empty list")
    return NoteFixture(
        title=str(raw.get("title") or "Untitled"),
        document_type=document_type,
        blocks=[_expand_heading(block) for block in blocks],
    )


def _expand_heading(block):
    """``"## Methods"`` -> a level-2 heading block; anything else as given."""
    if isinstance(block, str):
        match = _HEADING.match(block)
        if match:
            return {
                "type": "heading",
                "attrs": {"level": len(match.group(1))},
                "content": [match.group(2)],
            }
    return block


def _parse_expect(raw) -> Expectations:
    if not isinstance(raw, dict):
        raise CaseError("expect must be a mapping")
    _reject_unknown(raw, _EXPECT_KEYS, "expect")
    for key in ("tools_called", "tools_not_called", "unchanged_sections"):
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise CaseError(f"expect.{key} must be a list of strings")
    return Expectations(**raw)


def _reject_unknown(raw: dict, allowed: set, where: str) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise CaseError(f"unknown {where} keys: {sorted(unknown)}")
