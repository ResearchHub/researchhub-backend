"""Prompt builder for AI-generated proposal and RFP cover banners.

The banners copy the layout of RFP covers: a letter-spaced label, a heavy
title, a bold funding line and a light subtitle on the left, and a mark on the
right. Colors are left to the model, but each banner is given an art
direction picked at random (a palette mood, a background, a mark), so
generating again for the same details gives a different banner rather than
the same one.
"""

import random
from decimal import Decimal

from research_ai.prompts._loader import load_template


class CoverImagePrompts:
    # A longer subtitle crowds the banner; it is left out rather than cut mid-phrase.
    MAX_SUBTITLE_CHARS = 120

    LABELS = {
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

    # A logo only ever comes from the user's upload, sent along as a reference
    # image. Without one, an organization appears only as its name, so the
    # model never invents a logo or borrows another's.
    RIGHT_SIDE_WITH_LOGO = (
        "the provided logo, reproduced exactly, vertically centred, with lots of "
        "empty space around it."
    )
    RIGHT_SIDE_WITH_ORGANIZATION = (
        'the organization name "{organization}" set on its own in elegant, thin, '
        "tall capitals, vertically centred, with lots of empty space around it."
    )
    RIGHT_SIDE_PLAIN = (
        "{motif}, vertically centred, with lots of empty space all around."
    )

    # The art directions picked from. None names a color: the model chooses
    # them to suit the topic, and the logo when there is one.
    PALETTES = (
        "dark and deep, with light text",
        "light and airy, with dark text",
        "built around one bold, saturated hue",
        "of warm, earthy tones",
        "of cool, muted tones",
        "of two strongly contrasting hues",
    )
    BACKGROUNDS = (
        "A flat, plain background with the faintest subtle grain.",
        "A background of two flat tones meeting at one clean vertical or "
        "diagonal edge.",
        "A background of one very soft, barely visible gradient.",
        "A flat background with one large, faint shape bleeding off its right edge.",
    )
    MOTIFS = (
        "a few large, simple, softly overlapping geometric shapes",
        "a single bold abstract form inspired by the research topic",
        "a fine pattern of lines or dots that suggests the research topic",
        "a minimal abstract line illustration that suggests the research topic",
    )

    LOGO_RULE = (
        "- The attached reference image is the organization's logo. Reproduce it "
        "faithfully, with its exact shapes, lettering, colors and proportions, and "
        "choose the palette to suit it. Never alter it, and never draw any other "
        "logo, emblem, monogram or crest."
    )
    NO_LOGO_RULE = (
        "- Never draw a logo, emblem, monogram or crest for any organization; an "
        "organization appears only as its name in plain type."
    )

    @staticmethod
    def format_usd_compact(amount: Decimal) -> str:
        """``23000`` -> ``"$23K"``, ``1500000`` -> ``"$1.5M"``, ``900`` -> ``"$900"``"""
        for threshold, suffix in ((Decimal(1_000_000), "M"), (Decimal(1_000), "K")):
            if amount >= threshold:
                scaled = (amount / threshold).quantize(Decimal("0.1"))
                return f"${scaled.normalize():f}{suffix}"
        return f"${amount.quantize(Decimal(1)):f}"

    @staticmethod
    def quoted(text: str) -> str:
        """Text safe to put inside the prompt's double quotes, on one line."""
        return " ".join(text.replace('"', "'").split())

    @classmethod
    def build(
        cls,
        *,
        document_type: str,
        title: str,
        subtitle: str = "",
        organization: str = "",
        funding_amount_usd: Decimal | None = None,
        has_logo: bool = False,
        rng: random.Random | None = None,
    ) -> str:
        """The image prompt for one banner, its art direction picked with ``rng``."""
        rng = rng or random.Random()
        kind, label, funding_template = cls.LABELS[document_type]

        text_lines = [
            f'  1. A small label in widely letter-spaced capitals: "{label}"',
            f'  2. The title in large, heavy, tightly set type: "{cls.quoted(title)}"',
        ]
        if funding_amount_usd:
            funding = funding_template.format(
                amount=cls.format_usd_compact(funding_amount_usd)
            )
            text_lines.append(
                f"  {len(text_lines) + 1}. A funding line in bold type in an accent "
                f'color, about half the title size: "{funding}"'
            )
        subtitle = cls.quoted(subtitle)
        if subtitle and len(subtitle) <= cls.MAX_SUBTITLE_CHARS:
            text_lines.append(
                f'  {len(text_lines) + 1}. A subtitle in light, thin type: "{subtitle}"'
            )

        organization = cls.quoted(organization)
        if has_logo:
            right_side = cls.RIGHT_SIDE_WITH_LOGO
        elif organization:
            right_side = cls.RIGHT_SIDE_WITH_ORGANIZATION.format(
                organization=organization
            )
        else:
            right_side = cls.RIGHT_SIDE_PLAIN.format(motif=rng.choice(cls.MOTIFS))

        return load_template("cover_image.txt").format(
            kind=kind,
            text_lines="\n".join(text_lines),
            right_side=right_side,
            background=rng.choice(cls.BACKGROUNDS),
            # With a logo, the palette is chosen to suit it instead.
            palette="" if has_logo else f", {rng.choice(cls.PALETTES)}",
            logo_rule=cls.LOGO_RULE if has_logo else cls.NO_LOGO_RULE,
        )
