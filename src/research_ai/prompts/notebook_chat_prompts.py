"""Prompt builder for the notebook chat assistant.

The system prompt pins the agent to one note (id + title) and states the
tool contract: research via OpenAlex/web tools, note edits via read_note /
edit_note with full-document replaces. The user prompt is the user's chat
message verbatim, so there is no user-prompt builder here.
"""

from research_ai.prompts._loader import load_template
from researchhub_document.related_models.constants.document_type import PREREGISTRATION

_SELECTED_RFP_CAPABILITY = """## The selected RFP

This preregistration may have a funding opportunity selected. When the user's
request depends on that RFP's fit, requirements, budget, deadline, or wording,
call read_selected_rfp before answering or editing. Do not use search_grants to
guess which RFP is selected.

When the user asks to apply to a grant, switch to a different one, or drop the
current one, call set_selected_rfp with the grant id from search_grants (or
null to clear it), and say which RFP the note now applies to. Selecting is the
user's decision: confirm which one they mean rather than picking a search
result for them, and never set an RFP as a side effect of research."""


def build_notebook_chat_system_prompt(note) -> str:
    """The system prompt for a conversation attached to ``note``."""
    template = load_template("notebook_chat_system.txt")
    selected_rfp_capability = (
        _SELECTED_RFP_CAPABILITY if note.document_type == PREREGISTRATION else ""
    )
    return (
        template.replace("{{NOTE_ID}}", str(note.id))
        .replace("{{NOTE_TITLE}}", str(note.title or "Untitled"))
        .replace("{{SELECTED_RFP_CAPABILITY}}", selected_rfp_capability)
    )
