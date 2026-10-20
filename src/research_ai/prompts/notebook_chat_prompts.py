"""Prompt builder for the notebook chat assistant.

The system prompt pins the agent to one note by id and states the
tool contract: research via OpenAlex/web tools, note edits via bounded read_note /
edit_note block operations. It leaves out the title, which read_note returns,
so a rename does not change the prompt the provider caches. The user prompt is
the user's chat message verbatim, so there is no user-prompt builder here.
"""

from research_ai.prompts._loader import load_template
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)

_SELECTED_RFP_CAPABILITY = """## The selected RFP

This note is a research proposal (a preregistration). It may have a funding
opportunity selected. When the user's request depends on that RFP's fit,
requirements, budget, deadline, or wording, call read_selected_rfp before
answering or editing. Do not use search_grants to guess which RFP is selected.

When the user asks to apply to a grant, switch to a different one, or drop the
current one, call set_selected_rfp with the grant id from search_grants (or
null to clear it), and say which RFP the note now applies to. Selecting is the
user's decision: confirm which one they mean rather than picking a search
result for them, and never set an RFP as a side effect of research."""

_RFP_DETAILS_CAPABILITY = """## The RFP's Details

This note is an RFP draft. Besides the body you edit with edit_note, it has a
Details form the RFP is published with: funding amount (always USD),
organization, short description, contacts, and whether applications are private
or public. Call read_rfp_details to see what is filled in, and update_rfp_details
to change it; pass only the fields you are changing.

Set the amount, organization, contacts, or application visibility only to a
value the user gave or confirmed -- never invent one or write a placeholder.
When the user asks what the amount should be, suggest one in your reply and
wait for their yes before writing it. You may write the short description
yourself from the note body: say that you did, and when the body changes,
update the description to match. In your reply, name every Details field you
changed and its new value.

Publishing requires an amount and a description, and an RFP normally names at
least one contact, so tell the user which of those are still empty. Contacts
are ResearchHub users identified by user id: the only id you know without
being told is the current user's, which read_rfp_details returns. You cannot
publish the RFP; the user reviews the Details and publishes it themself."""

_CAPABILITY_BY_DOCUMENT_TYPE = {
    GRANT: _RFP_DETAILS_CAPABILITY,
    PREREGISTRATION: _SELECTED_RFP_CAPABILITY,
}


def build_notebook_chat_system_prompt(note) -> str:
    """The system prompt for a conversation attached to ``note``."""
    template = load_template("notebook_chat_system.txt")
    capability = _CAPABILITY_BY_DOCUMENT_TYPE.get(note.document_type, "")
    return template.replace("{{NOTE_ID}}", str(note.id)).replace(
        "{{DOCUMENT_TYPE_CAPABILITY}}", capability
    )
