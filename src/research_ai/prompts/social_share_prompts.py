from research_ai.prompts._loader import load_template


def build_share_post_system_prompt(max_chars: int) -> str:
    """System prompt for writing a social post that shares a proposal or RFP."""
    return load_template("social_share_post_system.txt").format(max_chars=max_chars)


def build_share_post_user_prompt(
    *,
    document_kind: str,
    title: str,
    body: str,
    details: list[str],
) -> str:
    """User prompt describing the document the post shares.

    ``details`` are short "Label: value" lines (funding amount, organization,
    deadline) that are only sometimes known. Every field is user-written, so
    angle brackets are escaped to keep it from closing ``<document>`` early.
    """
    lines = [f"Type: {document_kind}", f"Title: {title}", *details]
    document = "\n".join(lines) + f"\n\nDescription:\n{body}"
    return f"<document>\n{_escape_tags(document)}\n</document>\n\nWrite the post."


def _escape_tags(text: str) -> str:
    return text.replace("<", "&lt;").replace(">", "&gt;")
