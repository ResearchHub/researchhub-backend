from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from purchase.related_models.constants.currency import USD
from purchase.related_models.grant_model import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_document.related_models.constants.document_type import (
    CHANGELOG,
    DISCUSSION,
    GRANT,
    PAPER,
    PREREGISTRATION,
    QUESTION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.author_model import Author

_KIND_LABELS_AND_NOUNS = {
    CHANGELOG: ("Changelog", "a changelog"),
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
    is_discussion = document_type in (CHANGELOG, DISCUSSION)
    grant = (
        document.unified_document.grants.select_related("funding_pool").first()
        if document_type == GRANT
        else None
    )
    if is_discussion:
        owner = "ResearchHub"
    elif grant and grant.organization:
        owner = grant.organization
    else:
        owner = _get_first_author_name(document)

    cover = {
        "eyebrow": f"{kind} · {owner}" if owner else kind,
        "noun": noun,
        "title": title,
        "image_url": document.get_image_url(),
        "is_discussion": is_discussion,
    }
    if document_type == PREREGISTRATION:
        cover.update(_describe_fundraise(document))
    if grant:
        cover.update(_describe_grant_funding(grant))
    return cover


def _get_first_author_name(document: Paper | ResearchhubPost) -> str | None:
    """Return the name of the document's first credited author, if any."""
    if isinstance(document, Paper):
        author = Author.objects.filter(
            authorships__paper=document,
            authorships__author_position=Authorship.FIRST_AUTHOR_POSITION,
        ).first()
        return author.full_name if author else None
    link = (
        document.author_links.select_related("author")
        .filter(author__is_removed=False)
        .first()
    )
    return link.author.full_name if link else None


def _describe_fundraise(proposal: ResearchhubPost) -> dict:
    """Return the proposal's peer review rating, funding goal and progress toward it."""
    unified_document = proposal.unified_document
    fundraise = unified_document.fundraises.select_related("escrow").first()
    if fundraise is None:
        return {}

    figures = {}
    rating = unified_document.get_review_details()["avg"]
    if rating:
        figures["rating"] = f"{rating:.1f}"
    goal = float(fundraise.goal_amount)
    if goal > 0:
        raised = fundraise.get_amount_raised(currency=USD)
        figures["raising"] = format_compact_usd(goal)
        figures["progress"] = round(min(1, raised / goal) * 100)
    return figures


def _describe_grant_funding(grant: Grant) -> dict:
    """Return the RFP's budget plus what its funding pool has raised, in USD."""
    pool = getattr(grant, "funding_pool", None)
    pool_rsc = float(pool.amount_raised) if pool else 0
    pool_usd = RscExchangeRate.rsc_to_usd(pool_rsc) if pool_rsc > 0 else 0
    available = float(grant.amount) + pool_usd
    return {"available_funding": format_compact_usd(available)} if available > 0 else {}


def format_compact_usd(amount: float) -> str:
    """Shorten a USD amount the way the feed does: $850, $10K, $1.5M, $12M.

    Amounts under a dollar keep their cents so small contributions never read $0.
    """
    if amount < 0.01:
        return "<$0.01"
    if amount < 1:
        return f"${amount:.2f}"
    if amount < 1000:
        return f"${round(amount)}"
    if round(amount / 1000) < 1000:
        return f"${round(amount / 1000)}K"
    millions = amount / 1_000_000
    return f"${round(millions)}M" if millions >= 10 else f"${round(millions, 1):g}M"
