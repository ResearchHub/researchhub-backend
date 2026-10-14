from paper.related_models.paper_model import Paper
from purchase.related_models.constants.currency import USD
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PAPER,
    PREREGISTRATION,
    QUESTION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

_KIND_LABELS_AND_NOUNS = {
    PREREGISTRATION: ("Proposal", "a proposal"),
    GRANT: ("RFP", "an RFP"),
    PAPER: ("Paper", "a paper"),
    QUESTION: ("Question", "a question"),
    REGISTERED_REPORT: ("Registered report", "a registered report"),
}
_POST_LABEL_AND_NOUN = ("Post", "a post")


def build_work_cover(document: Paper | ResearchhubPost) -> dict:
    """Describe a document the way the activity feed draws its cover card."""
    if isinstance(document, Paper):
        document_type, title = PAPER, document.display_title
    else:
        document_type, title = document.document_type, document.title
    kind, noun = _KIND_LABELS_AND_NOUNS.get(document_type, _POST_LABEL_AND_NOUN)
    is_discussion = document_type == DISCUSSION
    owner = "ResearchHub" if is_discussion else _get_first_author_name(document)

    cover = {
        "eyebrow": f"{kind} · {owner}" if owner else kind,
        "noun": noun,
        "title": title,
        "image_url": document.get_image_url(),
        "is_discussion": is_discussion,
    }
    if document_type == PREREGISTRATION:
        cover.update(_describe_fundraise(document))
    return cover


def _get_first_author_name(document: Paper | ResearchhubPost) -> str | None:
    """Return the name of the document's first credited author, if any."""
    if isinstance(document, Paper):
        author = document.authors.first()
    else:
        author = next(iter(document.ordered_authors), None)
    return author.full_name if author else None


def _describe_fundraise(proposal: ResearchhubPost) -> dict:
    """Return the proposal's peer review rating, funding goal and progress toward it."""
    unified_document = proposal.unified_document
    fundraise = unified_document.fundraises.first()
    if fundraise is None:
        return {}

    figures = {}
    rating = unified_document.get_review_details()["avg"]
    if rating:
        figures["rating"] = f"{rating:.1f}"
    goal = float(fundraise.goal_amount)
    if goal > 0:
        raised = fundraise.get_amount_raised(currency=USD)
        figures["raising"] = _format_compact_usd(goal)
        figures["progress"] = round(min(1, raised / goal) * 100)
    return figures


def _format_compact_usd(amount: float) -> str:
    """Shorten a USD amount the way the feed does: $850, $10K, $1.5M, $12M."""
    if amount < 1000:
        return f"${round(amount)}"
    if round(amount / 1000) < 1000:
        return f"${round(amount / 1000)}K"
    millions = amount / 1_000_000
    return f"${round(millions)}M" if millions >= 10 else f"${round(millions, 1):g}M"
