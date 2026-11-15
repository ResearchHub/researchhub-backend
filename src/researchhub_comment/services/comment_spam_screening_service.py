from discussion.constants.flag_reasons import SPAM
from discussion.views import create_flag
from research_ai.services.message_screening.jev_client import JevClient
from researchhub_comment.models import RhCommentModel
from user.models import User
from user.services.risk_score_service import RiskScoreService

# Conservative while every flag goes straight to moderators; tune on their verdicts.
FLAG_THRESHOLD = 0.9
# Peer reviews run long; the intent shows well before this.
MAX_COMMENT_CHARS = 8_000

QUESTIONS = {
    "promotional": {
        "type": "noul",
        "instructions": (
            "Is this comment, posted on a scientific paper or research proposal, "
            "advertising a product, service, brand, or website, such as ads, SEO "
            "or affiliate links, or sales pitches?"
        ),
        "criteria": {
            "true": (
                "The comment mainly exists to promote, sell, or rank a product, "
                "service, brand, or website."
            ),
            "false": (
                "The comment is about research, even if it is critical, rude, "
                "short, low quality, or not in English. Links to papers, datasets, "
                "code, or the commenter's own related work, and mentions of a "
                "company, product, or funder, are not promotional."
            ),
        },
    },
    "solicitation": {
        "type": "noul",
        "instructions": (
            "Is this comment, posted on a scientific paper or research proposal, "
            "asking readers to get in touch or pay off the site, such as "
            "messaging on Telegram or WhatsApp, sending money or crypto, "
            "investment or fund recovery offers, or paid writing services?"
        ),
        "criteria": {
            "true": (
                "The comment solicits contact, money, or paid services off the site."
            ),
            "false": (
                "The comment does not solicit, even if it invites research "
                "collaboration or mentions funding, grants, or a funder."
            ),
        },
    },
}


class CommentSpamScreeningService:
    """Flags posted comments that read as spam for moderators to review."""

    def __init__(
        self,
        client: JevClient | None = None,
        risk_score_service: RiskScoreService | None = None,
    ) -> None:
        """Default to the configured Jev client and the real risk score service."""
        self.client = JevClient.from_settings() if client is None else client
        self.risk_score_service = risk_score_service or RiskScoreService()

    def screen(self, comment: RhCommentModel) -> None:
        """Flag the comment as spam when any Jev score reaches the threshold."""
        if self.client is None or self.risk_score_service.is_trusted(
            comment.created_by
        ):
            return
        flagger = User.objects.get_ai_expert_account()
        if comment.flags.filter(created_by=flagger).exists():
            return
        state = {"comment": comment.plain_text[:MAX_COMMENT_CHARS]}
        answers = self.client.decide(state, QUESTIONS).answers
        if max(answers.values()) >= FLAG_THRESHOLD:
            create_flag(
                user=flagger,
                item=comment,
                reason=SPAM,
                reason_choice=SPAM,
                reason_memo=_describe_scores(answers),
            )


def _describe_scores(answers: dict[str, float]) -> str:
    """Summarize Jev's scores for the moderator reading the flag memo."""
    scores = ", ".join(f"{name} {score:.2f}" for name, score in answers.items())
    return f"Auto-flagged by the spam filter: {scores}"
