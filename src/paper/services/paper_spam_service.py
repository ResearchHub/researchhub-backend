"""Score user-uploaded papers for spam, without changing them.

Each paper gets a heuristic score from its metadata and its uploader, and
optionally a verdict from the Jev decision model. Scores only feed a report; no
paper is removed here.
"""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from django.db.models import Count, QuerySet
from django.db.models.functions import Lower, TruncDate

from paper.models import Paper
from research_ai.services.message_screening.jev_client import DecisionError, JevClient

logger = logging.getLogger(__name__)

# Starting points; tune them on a hand-labelled sample before acting on them.
SPAM_THRESHOLD = 0.7
REVIEW_THRESHOLD = 0.3
CLASSIFIER_SPAM_THRESHOLD = 0.9
CLASSIFIER_REVIEW_THRESHOLD = 0.5

# Signal weights, summed and capped at 1.0.
WEIGHTS = {
    "uploader_flagged": 0.6,
    "promotional_terms": 0.4,
    "link_in_title": 0.4,
    "contact_details": 0.4,
    "links_in_abstract": 0.2,
    "burst_uploader": 0.2,
    "shared_title": 0.2,
    "thin_metadata": 0.15,
    "new_account": 0.1,
    "no_pdf": 0.1,
    "no_authors": 0.1,
}

BURST_UPLOADS_PER_DAY = 10
SHARED_TITLE_UPLOADERS = 3
NEW_ACCOUNT_AGE = timedelta(days=1)
THIN_ABSTRACT_CHARS = 100
ABSTRACT_LINKS = 2

# Commercial phrases only: bare topics such as loans, CBD, keto, dating, or
# gambling are also research subjects, so they are left to the classifier.
PROMOTIONAL_TERMS = re.compile(
    r"\b("
    r"online casino|casino bonus|betting tips|slot games?|jackpot"
    r"|escorts? service|call girls?|buy viagra|cialis|gummies"
    r"|payday loans?|instant loans?|credit repair|crypto signals|binary options"
    r"|buy (?:cheap|online|now)|best price|coupon|promo code|free trial"
    r"|essay writing service|write my (?:essay|paper)|assignment help"
    r"|homework help|seo services?|backlinks?|buy (?:followers|likes)"
    r"|customer (?:care|service) (?:number|helpline)|toll[- ]free|helpline"
    r"|packers and movers|plumbing services?|locksmith|repair services?"
    r")\b",
    re.IGNORECASE,
)
URL = re.compile(
    r"https?://|www\.|\b[\w-]+\.(?:com|net|org|io|shop|xyz|in)\b", re.IGNORECASE
)
SCHOLARLY_URL = re.compile(
    r"doi\.org|arxiv\.org|biorxiv\.org|medrxiv\.org|ncbi\.nlm\.nih\.gov|github\.com",
    re.IGNORECASE,
)
# A dialable number (+44 20 7946 0958, 1-800-555-0199, (555) 555-0199), not a
# run of years or figures, which abstracts are full of.
PHONE = re.compile(
    r"\+\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b"
    r"|\b1[\s.-]8\d\d[\s.-]\d{3}[\s.-]\d{4}\b"
    r"|\(\d{3}\)\s?\d{3}[\s.-]\d{4}\b"
)

CLASSIFIER_ABSTRACT_CHARS = 4_000
CLASSIFIER_AUTHORS = 10

QUESTIONS = {
    "not_research": {
        "type": "noul",
        "instructions": (
            "ResearchHub hosts scientific papers and other scholarly work. "
            "Judging the title, abstract, and metadata of this upload: is it "
            "something other than a scholarly or scientific work?"
        ),
        "criteria": {
            "true": (
                "It is advertising, a product or service listing, SEO or link "
                "spam, gibberish, a personal message, or other non-research "
                "content."
            ),
            "false": (
                "It is a research paper, preprint, review, thesis, report, "
                "essay, or other scholarly work, even if short, low quality, "
                "unconventional, speculative, or fringe."
            ),
        },
    },
    "promotional": {
        "type": "noul",
        "instructions": (
            "Judging the title, abstract, and metadata of this upload: is its "
            "main purpose to promote, sell, or rank a product, service, brand, "
            "or website?"
        ),
        "criteria": {
            "true": "It mainly promotes or sells something, or links to a site.",
            "false": (
                "It is not promotional, even if it names a company, product, or funder."
            ),
        },
    },
}


class Verdict(StrEnum):
    SPAM = "spam"
    REVIEW = "review"
    KEEP = "keep"


class ClassifyScope(StrEnum):
    NONE = "none"
    # Only papers the heuristics leave in the review band.
    UNCLEAR = "unclear"
    ALL = "all"


@dataclass
class PaperSpamScore:
    paper: Paper
    heuristic_score: float
    reasons: list[str] = field(default_factory=list)
    not_research: float | None = None
    promotional: float | None = None
    classifier_error: str = ""
    cost_microusd: int | None = None

    @property
    def classifier_score(self) -> float | None:
        scores = [s for s in (self.not_research, self.promotional) if s is not None]
        return max(scores) if scores else None

    @property
    def verdict(self) -> Verdict:
        classifier = self.classifier_score
        if self.heuristic_score >= SPAM_THRESHOLD or (
            classifier is not None and classifier >= CLASSIFIER_SPAM_THRESHOLD
        ):
            return Verdict.SPAM
        if self.heuristic_score >= REVIEW_THRESHOLD or (
            classifier is not None and classifier >= CLASSIFIER_REVIEW_THRESHOLD
        ):
            return Verdict.REVIEW
        return Verdict.KEEP


class PaperSpamService:
    """Scores user-uploaded papers; reads only, never removes."""

    def __init__(self, client: JevClient | None = None):
        self.client = JevClient.from_settings() if client is None else client

    @staticmethod
    def user_uploaded_papers() -> QuerySet[Paper]:
        return Paper.objects.filter(
            uploaded_by__isnull=False,
            retrieved_from_external_source=False,
            is_removed=False,
        )

    def score_all(
        self,
        papers: QuerySet[Paper] | None = None,
        classify: ClassifyScope = ClassifyScope.NONE,
    ) -> Iterator[PaperSpamScore]:
        papers = self.user_uploaded_papers() if papers is None else papers
        if classify != ClassifyScope.NONE and self.client is None:
            raise ValueError("Classifying needs OPENROUTER_API_KEY to be set.")
        burst_uploaders = self._burst_uploaders(papers)
        shared_titles = self._shared_titles(papers)
        rows = (
            papers.select_related("uploaded_by", "unified_document")
            .annotate(author_count=Count("authors"))
            .order_by("id")
        )
        for paper in rows.iterator(chunk_size=1_000):
            score = self.score(paper, burst_uploaders, shared_titles)
            if classify == ClassifyScope.ALL or (
                classify == ClassifyScope.UNCLEAR and score.verdict == Verdict.REVIEW
            ):
                self.classify(score)
            yield score

    def score(
        self,
        paper: Paper,
        burst_uploaders: set[int],
        shared_titles: dict[str, int],
    ) -> PaperSpamScore:
        reasons = []
        uploader = paper.uploaded_by
        title = paper.title or paper.paper_title or ""
        abstract = paper.abstract or ""
        text = f"{title}\n{abstract}"

        if uploader and (uploader.probable_spammer or uploader.is_suspended):
            reasons.append("uploader_flagged")
        terms = sorted({m.lower() for m in PROMOTIONAL_TERMS.findall(text)})
        if terms:
            reasons.append(f"promotional_terms:{','.join(terms[:5])}")
        if _non_scholarly_links(title):
            reasons.append("link_in_title")
        if PHONE.search(text):
            reasons.append("contact_details")
        if _non_scholarly_links(abstract) >= ABSTRACT_LINKS:
            reasons.append("links_in_abstract")
        if uploader and uploader.id in burst_uploaders:
            reasons.append("burst_uploader")
        uploaders = shared_titles.get(title.strip().lower(), 0)
        if uploaders >= SHARED_TITLE_UPLOADERS:
            reasons.append(f"shared_title:{uploaders}")
        if not paper.doi and len(abstract.strip()) < THIN_ABSTRACT_CHARS:
            reasons.append("thin_metadata")
        if (
            uploader
            and paper.created_date
            and paper.created_date - uploader.date_joined < NEW_ACCOUNT_AGE
        ):
            reasons.append("new_account")
        if not paper.file and not paper.pdf_url:
            reasons.append("no_pdf")
        if not paper.raw_authors and not getattr(paper, "author_count", 0):
            reasons.append("no_authors")

        total = sum(WEIGHTS[reason.split(":")[0]] for reason in reasons)
        return PaperSpamScore(
            paper=paper, heuristic_score=round(min(total, 1.0), 2), reasons=reasons
        )

    def classify(self, score: PaperSpamScore) -> None:
        """Adds Jev's answers to the score; an error leaves the heuristics alone."""
        try:
            decision = self.client.decide(_state(score.paper), QUESTIONS)
        except DecisionError as exc:
            logger.warning("could not classify paper %s: %s", score.paper.id, exc)
            score.classifier_error = str(exc)
            return
        score.not_research = decision.answers["not_research"]
        score.promotional = decision.answers["promotional"]
        score.cost_microusd = decision.cost_microusd

    @staticmethod
    def _burst_uploaders(papers: QuerySet[Paper]) -> set[int]:
        """Uploaders who uploaded many papers on a single day."""
        # Postgres can't take Max over Count in one query; fold the days here.
        most: dict[int, int] = {}
        for row in (
            papers.annotate(day=TruncDate("created_date"))
            .values("uploaded_by_id", "day")
            .annotate(n=Count("id"))
            .order_by()
        ):
            uploader = row["uploaded_by_id"]
            most[uploader] = max(most.get(uploader, 0), row["n"])
        return {uid for uid, n in most.items() if n >= BURST_UPLOADS_PER_DAY}

    @staticmethod
    def _shared_titles(papers: QuerySet[Paper]) -> dict[str, int]:
        """Lower-cased titles uploaded by several accounts, with their count."""
        rows = (
            papers.annotate(key=Lower("title"))
            .values("key")
            .annotate(uploaders=Count("uploaded_by_id", distinct=True))
            .filter(uploaders__gte=SHARED_TITLE_UPLOADERS)
            .order_by()
        )
        return {row["key"].strip(): row["uploaders"] for row in rows if row["key"]}


def _non_scholarly_links(text: str) -> int:
    return sum(
        1
        for match in URL.finditer(text)
        if not SCHOLARLY_URL.search(text[match.start() : match.start() + 60])
    )


def _state(paper: Paper) -> dict:
    authors = paper.raw_authors if isinstance(paper.raw_authors, list) else []
    names = []
    for author in authors[:CLASSIFIER_AUTHORS]:
        if isinstance(author, dict):
            name = " ".join(
                str(author.get(k) or "") for k in ("first_name", "last_name")
            ).strip()
            names.append(name or str(author.get("full_name") or ""))
        else:
            names.append(str(author))
    state = {
        "title": paper.title or "",
        "abstract": (paper.abstract or "")[:CLASSIFIER_ABSTRACT_CHARS],
        "has_pdf": bool(paper.file or paper.pdf_url),
    }
    if paper.paper_title and paper.paper_title != paper.title:
        state["official_title"] = paper.paper_title
    if paper.doi:
        state["doi"] = paper.doi
    if paper.url:
        state["url"] = paper.url
    if names := [n for n in names if n]:
        state["authors"] = names
    return state
