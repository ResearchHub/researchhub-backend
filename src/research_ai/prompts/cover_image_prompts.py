"""Prompt builder for AI-generated proposal and RFP cover banners.

The banners copy the layout of RFP covers: a letter-spaced label, a heavy
title, a bold funding line and a light subtitle on the left, and a mark on the
right. Colors are left to the model. Each variant changes only
the right-hand mark so the options differ while the text stays the same.
"""

from decimal import Decimal

from research_ai.prompts._loader import load_template

# A longer subtitle crowds the banner; it is left out rather than cut mid-phrase.
MAX_SUBTITLE_CHARS = 120

_LABELS = {
    "GRANT": (
        "request for proposals",
        "REQUEST FOR PROPOSALS",
        "Up to {amount} in funding",
    ),
    "PREREGISTRATION": (
        "research proposal",
        "RESEARCH PROPOSAL",
        "Seeking {amount} in funding",
    ),
}

# An organization appears only as its name: a logo comes from an uploaded cover,
# never from generation, which would invent one or borrow another's.
_RIGHT_SIDE_WITH_ORGANIZATION = (
    'the organization name "{organization}" set on its own in elegant, thin, '
    "tall capitals, vertically centred, with lots of empty space around it.",
    "a delicate fine-line illustration evoking the research topic, drawn "
    "with thin single-weight strokes, with the organization name "
    '"{organization}" in thin capitals beneath it.',
    "an abstract constellation of thin lines and small dots suggesting a "
    'molecular or network structure, with the organization name "{organization}" '
    "in small thin capitals beneath it.",
)

_RIGHT_SIDE_WITHOUT_ORGANIZATION = (
    "a few large, simple, softly overlapping geometric shapes, vertically "
    "centred, with lots of empty space around them.",
    "a delicate fine-line illustration evoking the research topic, drawn "
    "with thin single-weight strokes, vertically centred.",
    "an abstract constellation of thin lines and small dots suggesting a "
    "molecular or network structure, vertically centred.",
)

VARIANT_COUNT = len(_RIGHT_SIDE_WITHOUT_ORGANIZATION)


def format_usd_compact(amount: Decimal) -> str:
    """``23000`` -> ``"$23K"``, ``1500000`` -> ``"$1.5M"``, ``900`` -> ``"$900"``."""
    for threshold, suffix in ((Decimal(1_000_000), "M"), (Decimal(1_000), "K")):
        if amount >= threshold:
            scaled = (amount / threshold).quantize(Decimal("0.1"))
            return f"${scaled.normalize():f}{suffix}"
    return f"${amount.quantize(Decimal(1)):f}"


def _quoted(text: str) -> str:
    """Text safe to put inside the prompt's double quotes, on one line."""
    return " ".join(text.replace('"', "'").split())


def build_cover_image_prompts(
    *,
    document_type: str,
    title: str,
    subtitle: str = "",
    organization: str = "",
    funding_amount_usd: Decimal | None = None,
) -> list[str]:
    """One image prompt per variant, all sharing the same text."""
    kind, label, funding_template = _LABELS[document_type]

    text_lines = [
        f'  1. A small label in widely letter-spaced capitals: "{label}"',
        f'  2. The title in large, heavy, tightly set type: "{_quoted(title)}"',
    ]
    if funding_amount_usd:
        funding = funding_template.format(amount=format_usd_compact(funding_amount_usd))
        text_lines.append(
            f"  {len(text_lines) + 1}. A funding line in bold type in an accent "
            f'color, about half the title size: "{funding}"'
        )
    subtitle = _quoted(subtitle)
    if subtitle and len(subtitle) <= MAX_SUBTITLE_CHARS:
        text_lines.append(
            f'  {len(text_lines) + 1}. A subtitle in light, thin type: "{subtitle}"'
        )

    organization = _quoted(organization)
    if organization:
        right_sides = [
            side.format(organization=organization)
            for side in _RIGHT_SIDE_WITH_ORGANIZATION
        ]
    else:
        right_sides = list(_RIGHT_SIDE_WITHOUT_ORGANIZATION)

    template = load_template("cover_image.txt")
    return [
        template.format(kind=kind, text_lines="\n".join(text_lines), right_side=side)
        for side in right_sides
    ]
