from discussion.constants.flag_reasons import SPAM
from discussion.views import create_flag
from research_ai.services.message_screening.jev_client import JevClient
from researchhub_comment.models import CommentSpamScreening, RhCommentModel
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
    "off_topic": {
        "type": "noul",
        "instructions": (
            "Is this comment unrelated to both research and the document it is "
            "posted on, whose title is given, such as gibberish, a test post, or "
            "text about an unrelated topic?"
        ),
        "criteria": {
            "true": (
                "The comment is gibberish, a test post, or about a topic unrelated "
                "to both research and the document's title."
            ),
            "false": (
                "The comment relates to research or to the document, even if it is "
                "short, vague, critical, rude, low quality, or not in English, "
                "such as praise, thanks, agreement, a personal experience with the "
                "topic, or a question for the authors or other commenters."
            ),
        },
    },
}


class CommentSpamScreeningService:
    """Screens comments with Jev, recording every result and flagging the spam."""

    def __init__(
        self,
        client: JevClient | None = None,
        risk_score_service: RiskScoreService | None = None,
    ) -> None:
        """Default to the configured Jev client and the real risk score service."""
        self.client = client or JevClient.from_settings()
        self.risk_score_service = risk_score_service or RiskScoreService()

    def screen(self, comment: RhCommentModel) -> None:
        """Record Jev's spam scores for the comment, flagging it at the threshold."""
        if self.client is None or self.risk_score_service.is_trusted(
            comment.created_by
        ):
            return
        state = {
            "document_title": comment.unified_document.get_display_title(),
            "comment": comment.plain_text[:MAX_COMMENT_CHARS],
        }
        decision = self.client.decide(state, QUESTIONS)
        screening = CommentSpamScreening.objects.create(
            comment=comment,
            model=decision.model,
            promotional=decision.answers["promotional"],
            solicitation=decision.answers["solicitation"],
            off_topic=decision.answers["off_topic"],
            flagged=max(decision.answers.values()) >= FLAG_THRESHOLD,
            cost_microusd=decision.cost_microusd,
        )
        flagger = User.objects.get_ai_expert_account()
        if screening.flagged and not comment.flags.filter(created_by=flagger).exists():
            create_flag(
                user=flagger,
                item=comment,
                reason=SPAM,
                reason_choice=SPAM,
                reason_memo=_describe_scores(decision.answers),
            )


def _describe_scores(answers: dict[str, float]) -> str:
    """Summarize Jev's scores for the moderator reading the flag memo."""
    scores = ", ".join(f"{name} {score:.2f}" for name, score in answers.items())
    return f"Auto-flagged by the spam filter: {scores}"
