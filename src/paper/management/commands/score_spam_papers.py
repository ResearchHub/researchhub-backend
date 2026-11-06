import csv
from collections import Counter, defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from paper.services.paper_spam_service import (
    ClassifyScope,
    PaperSpamService,
    Verdict,
)

PAPER_COLUMNS = [
    "paper_id",
    "unified_document_id",
    "uploaded_by_id",
    "created_date",
    "moderation_status",
    "verdict",
    "heuristic_score",
    "reasons",
    "not_research",
    "promotional",
    "classifier_error",
    "doi",
    "title",
]
UPLOADER_COLUMNS = [
    "uploaded_by_id",
    "uploader_flagged",
    "papers",
    "spam",
    "review",
    "keep",
    "spam_share",
]


class Command(BaseCommand):
    help = (
        "Score user-uploaded papers for spam and write the scores to CSV. "
        "Reads only: no paper or user is changed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            help="Paper scores CSV path; an _uploaders.csv is written next to it.",
        )
        parser.add_argument(
            "--classify",
            choices=[scope.value for scope in ClassifyScope],
            default=ClassifyScope.NONE.value,
            help=(
                "Also ask the Jev decision model (needs OPENROUTER_API_KEY): "
                "'unclear' for papers the heuristics put in review, 'all' for "
                "every paper. Default: none."
            ),
        )
        parser.add_argument(
            "--limit", type=int, help="Score only the first N papers by id."
        )

    def handle(self, *args, **options):
        stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        papers_path = Path(options["output"] or f"paper_spam_scores_{stamp}.csv")
        uploaders_path = papers_path.with_name(f"{papers_path.stem}_uploaders.csv")
        classify = ClassifyScope(options["classify"])

        service = PaperSpamService()
        if classify != ClassifyScope.NONE and service.client is None:
            raise CommandError("--classify needs OPENROUTER_API_KEY to be set.")
        papers = service.user_uploaded_papers()
        if options["limit"]:
            limited = papers.order_by("id").values_list("id", flat=True)
            papers = papers.filter(id__in=list(limited[: options["limit"]]))
        total = papers.count()
        self.stdout.write(f"Scoring {total} user-uploaded papers (classify={classify})")

        verdicts = Counter()
        per_uploader = defaultdict(Counter)
        uploader_flagged = {}
        classified = cost = 0
        scores = service.score_all(papers, classify=classify)
        with papers_path.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(PAPER_COLUMNS)
            for done, score in enumerate(scores, start=1):
                paper = score.paper
                verdict = score.verdict
                writer.writerow(_paper_row(score, verdict))
                verdicts[verdict] += 1
                per_uploader[paper.uploaded_by_id][verdict] += 1
                uploader = paper.uploaded_by
                uploader_flagged[paper.uploaded_by_id] = bool(
                    uploader and (uploader.probable_spammer or uploader.is_suspended)
                )
                if score.not_research is not None:
                    classified += 1
                    cost += score.cost_microusd or 0
                if done % 1_000 == 0:
                    self.stdout.write(f"  {done}/{total}")

        with uploaders_path.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(UPLOADER_COLUMNS)
            rows = sorted(
                per_uploader.items(),
                key=lambda item: (-item[1][Verdict.SPAM], -item[1].total()),
            )
            for uploader_id, counts in rows:
                count = counts.total()
                writer.writerow(
                    [
                        uploader_id,
                        uploader_flagged[uploader_id],
                        count,
                        counts[Verdict.SPAM],
                        counts[Verdict.REVIEW],
                        counts[Verdict.KEEP],
                        f"{counts[Verdict.SPAM] / count:.2f}",
                    ]
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"spam={verdicts[Verdict.SPAM]} review={verdicts[Verdict.REVIEW]} "
                f"keep={verdicts[Verdict.KEEP]} across {len(per_uploader)} uploaders"
            )
        )
        if classified:
            self.stdout.write(
                f"Classified {classified} papers for ${cost / 1_000_000:.2f}"
            )
        self.stdout.write(f"Wrote {papers_path} and {uploaders_path}")


def _paper_row(score, verdict) -> list:
    paper = score.paper
    document = paper.unified_document
    return [
        paper.id,
        paper.unified_document_id,
        paper.uploaded_by_id,
        paper.created_date.isoformat() if paper.created_date else "",
        document.status if document else "",
        verdict,
        score.heuristic_score,
        ";".join(score.reasons),
        _probability(score.not_research),
        _probability(score.promotional),
        score.classifier_error,
        _cell(paper.doi or ""),
        _cell(paper.title or paper.paper_title or ""),
    ]


def _probability(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def _cell(text: str) -> str:
    """Uploaded text, kept from running as a formula when opened in a spreadsheet."""
    text = " ".join(text.split())
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") else text
