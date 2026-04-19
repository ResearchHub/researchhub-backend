import io
import re
from typing import Any, Mapping
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ai_peer_review.constants import CATEGORY_ITEMS, CATEGORY_KEYS
from ai_peer_review.models import ProposalReview

COLOR_HIGH = colors.HexColor("#27AE60")
COLOR_MEDIUM = colors.HexColor("#F39C12")
COLOR_LOW = colors.HexColor("#E74C3C")
COLOR_NA = colors.HexColor("#95A5A6")
COLOR_TABLE_HEADER = colors.HexColor("#6F42C1")


def _xml_text(text: object) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    return escape(s).replace("\n", "<br/>")


def _humanize_key(key: str) -> str:
    s = (key or "").replace("_", " ").strip()
    return s.title() if s else ""


def _category_score_color(score: object) -> colors.Color:
    if score is None:
        return COLOR_NA
    s = str(score).strip().lower()
    if s in ("high", "excellent"):
        return COLOR_HIGH
    if s in ("medium", "good"):
        return COLOR_MEDIUM
    if s in ("low", "poor"):
        return COLOR_LOW
    if s in ("n/a", "na"):
        return COLOR_NA
    return COLOR_NA


def _decision_color(decision: object) -> colors.Color:
    if decision is None:
        return COLOR_NA
    d = str(decision).strip().lower()
    if d == "yes":
        return COLOR_HIGH
    if d == "partial":
        return COLOR_MEDIUM
    if d == "no":
        return COLOR_LOW
    if d in ("n/a", "na"):
        return COLOR_NA
    return COLOR_NA


def _ordered_category_keys(categories: Mapping[str, Any] | None) -> list[str]:
    if not categories:
        return []
    keys = [k for k in categories if isinstance(k, str)]
    known = [k for k in CATEGORY_KEYS if k in keys]
    rest = sorted(k for k in keys if k not in set(CATEGORY_KEYS))
    return known + rest


def _ordered_item_keys(category_key: str, items: Mapping[str, Any] | None) -> list[str]:
    if not items:
        return []
    keys = [k for k in items if isinstance(k, str)]
    preferred = CATEGORY_ITEMS.get(category_key, ())
    seen: set[str] = set()
    ordered: list[str] = []
    for k in preferred:
        if k in keys:
            ordered.append(k)
            seen.add(k)
    for k in sorted(keys):
        if k not in seen:
            ordered.append(k)
    return ordered


def merged_review_payload(
    result_data: dict,
    overall_rating: str | None,
    overall_score_numeric: int | None,
    overall_rationale: str | None = None,
    overall_confidence: str | None = None,
) -> dict:
    """Prefer authoritative model fields when building a display dict."""
    data = dict(result_data or {})
    if overall_rating is not None:
        data["overall_rating"] = overall_rating
    if overall_score_numeric is not None:
        data["overall_score_numeric"] = overall_score_numeric
    if overall_rationale is not None:
        data["overall_rationale"] = overall_rationale
    if overall_confidence is not None:
        data["overall_confidence"] = overall_confidence
    return data


def safe_pdf_filename_part(title: str, max_len: int = 80) -> str:
    base = re.sub(r"[^\w\s-]", "", (title or "proposal").strip())[:max_len]
    base = re.sub(r"[-\s]+", "-", base).strip("-") or "proposal"
    return base


def build_proposal_review_pdf_bytes(
    review_dict: dict,
    document_title: str,
    *,
    editorial_feedback: dict | None = None,
) -> bytes:
    buffer = io.BytesIO()
    safe_title = (document_title or "proposal")[:200]
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"Proposal Review - {safe_title}",
        author="",
    )
    page_width = letter[0] - 1.5 * inch
    base_styles = getSampleStyleSheet()
    styles = {
        "normal": ParagraphStyle(
            "normal",
            parent=base_styles["Normal"],
            fontSize=9,
            leading=13,
            alignment=TA_LEFT,
        ),
        "small": ParagraphStyle(
            "small", parent=base_styles["Normal"], fontSize=8, leading=11
        ),
        "bold": ParagraphStyle(
            "bold",
            parent=base_styles["Normal"],
            fontSize=9,
            leading=13,
            fontName="Helvetica-Bold",
        ),
        "section_heading": ParagraphStyle(
            "section_heading",
            parent=base_styles["Normal"],
            fontSize=11,
            fontName="Helvetica-Bold",
            spaceBefore=6,
            spaceAfter=4,
            textColor=colors.HexColor("#2C3E50"),
        ),
        "sub_heading": ParagraphStyle(
            "sub_heading",
            parent=base_styles["Normal"],
            fontSize=9,
            fontName="Helvetica-Bold",
            spaceBefore=4,
        ),
        "badge": ParagraphStyle(
            "badge",
            parent=base_styles["Normal"],
            fontSize=9,
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
        ),
        "title": ParagraphStyle(
            "title",
            parent=base_styles["Normal"],
            fontSize=14,
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
            textColor=colors.HexColor("#2C3E50"),
            spaceBefore=6,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base_styles["Normal"],
            fontSize=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#7F8C8D"),
            spaceAfter=10,
        ),
        "table_header": ParagraphStyle(
            "table_header",
            parent=base_styles["Normal"],
            fontSize=8,
            leading=11,
            fontName="Helvetica-Bold",
            textColor=colors.white,
        ),
        "table_header_center": ParagraphStyle(
            "table_header_center",
            parent=base_styles["Normal"],
            fontSize=8,
            leading=11,
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
            textColor=colors.white,
        ),
    }

    def section_header(text: str) -> list:
        return [
            Spacer(1, 0.15 * inch),
            HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2C3E50")),
            Paragraph(_xml_text(text), styles["section_heading"]),
            Spacer(1, 0.05 * inch),
        ]

    elements: list = []
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(_xml_text("Proposal Review Report"), styles["title"]))
    elements.append(
        Paragraph(
            _xml_text(safe_title),
            styles["subtitle"],
        )
    )

    elements += section_header("Section A — Overall assessment")
    overall_rating = review_dict.get("overall_rating", "N/A")
    overall_score = review_dict.get("overall_score_numeric", "N/A")
    rating_color = _category_score_color(overall_rating)
    rating_hex = "#{:02X}{:02X}{:02X}".format(
        int(rating_color.red * 255),
        int(rating_color.green * 255),
        int(rating_color.blue * 255),
    )
    or_label = _xml_text(str(overall_rating))
    or_score = _xml_text(str(overall_score))
    rating_table = Table(
        [
            [
                Paragraph(
                    f'<font color="{rating_hex}"><b>{or_label}</b></font>  '
                    f'<font color="#7F8C8D">(score {or_score} / 3)</font>',
                    styles["bold"],
                ),
                Paragraph("", styles["normal"]),
            ]
        ],
        colWidths=[2.0 * inch, page_width - 2.0 * inch],
    )
    rating_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F8F9FA")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
            ]
        )
    )
    elements.append(rating_table)
    elements.append(Spacer(1, 0.06 * inch))

    oc = review_dict.get("overall_confidence")
    if oc:
        elements.append(
            Paragraph(
                f"<b>Confidence</b>: {_xml_text(oc)}",
                styles["normal"],
            )
        )
    summary = review_dict.get("overall_summary") or ""
    if summary:
        elements.append(Paragraph("<b>Summary</b>", styles["sub_heading"]))
        elements.append(Paragraph(_xml_text(summary), styles["normal"]))
        elements.append(Spacer(1, 0.05 * inch))
    rationale = review_dict.get("overall_rationale") or ""
    if rationale:
        elements.append(Paragraph("<b>Overall rationale</b>", styles["sub_heading"]))
        elements.append(Paragraph(_xml_text(rationale), styles["normal"]))
        elements.append(Spacer(1, 0.05 * inch))

    def bullet_list(title: str, items: list | None):
        if not items:
            return
        elements.append(Paragraph(f"<b>{_xml_text(title)}</b>", styles["sub_heading"]))
        for i, line in enumerate(items, 1):
            elements.append(Paragraph(_xml_text(f"{i}. {line}"), styles["normal"]))
        elements.append(Spacer(1, 0.05 * inch))

    bullet_list("Major strengths", review_dict.get("major_strengths") or [])
    bullet_list("Major weaknesses", review_dict.get("major_weaknesses") or [])
    bullet_list("Fatal flaws", review_dict.get("fatal_flaws") or [])

    elements += section_header("Section B — Category assessments")
    cats = review_dict.get("categories") or {}
    if not cats:
        elements.append(
            Paragraph("No category assessments in this review.", styles["normal"])
        )
    for cat_key in _ordered_category_keys(cats):
        cat = cats.get(cat_key) or {}
        if not isinstance(cat, dict):
            continue
        cat_label = _humanize_key(cat_key)
        dim_score = cat.get("score", "N/A")
        dim_rationale = cat.get("rationale", "")
        dim_color = _category_score_color(dim_score)
        dim_hex = "#{:02X}{:02X}{:02X}".format(
            int(dim_color.red * 255),
            int(dim_color.green * 255),
            int(dim_color.blue * 255),
        )
        elements.append(
            Paragraph(
                f"<b>{_xml_text(cat_label)}</b>  "
                f'<font color="{dim_hex}">| {_xml_text(dim_score)}</font>',
                styles["sub_heading"],
            )
        )
        if dim_rationale:
            elements.append(Paragraph(_xml_text(dim_rationale), styles["small"]))
        elements.append(Spacer(1, 0.04 * inch))

        items = cat.get("items") or {}
        if not isinstance(items, dict):
            items = {}
        table_data = [
            [
                Paragraph("Item", styles["table_header"]),
                Paragraph("Decision", styles["table_header_center"]),
                Paragraph("Justification", styles["table_header"]),
            ]
        ]
        for item_key in _ordered_item_keys(cat_key, items):
            row = items.get(item_key)
            if not isinstance(row, dict):
                row = {}
            decision = row.get("decision", "N/A")
            justification = row.get("justification", "")
            item_label = _humanize_key(item_key)
            dec_color = _decision_color(decision)
            dec_hex = "#{:02X}{:02X}{:02X}".format(
                int(dec_color.red * 255),
                int(dec_color.green * 255),
                int(dec_color.blue * 255),
            )
            table_data.append(
                [
                    Paragraph(_xml_text(item_label), styles["small"]),
                    Paragraph(
                        f'<font color="{dec_hex}"><b>{_xml_text(decision)}</b></font>',
                        styles["badge"],
                    ),
                    Paragraph(_xml_text(justification), styles["small"]),
                ]
            )
        col_widths = [1.5 * inch, 0.85 * inch, page_width - 2.35 * inch]
        sa_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        sa_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.HexColor("#F8F9FA"), colors.white],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BDC3C7")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        elements.append(sa_table)
        elements.append(Spacer(1, 0.1 * inch))

    if editorial_feedback:
        elements += section_header("Section C — Editorial feedback")
        insights = editorial_feedback.get("expert_insights") or ""
        if insights:
            elements.append(Paragraph(_xml_text(insights), styles["normal"]))
            elements.append(Spacer(1, 0.06 * inch))
        cat_rows = editorial_feedback.get("categories") or []
        if cat_rows:
            ed_data = [
                [
                    Paragraph("Category", styles["table_header"]),
                    Paragraph("Editor score", styles["table_header_center"]),
                ]
            ]
            for row in cat_rows:
                if not isinstance(row, dict):
                    continue
                code = row.get("category_code", "")
                escore = row.get("score", "")
                ed_data.append(
                    [
                        Paragraph(_xml_text(_humanize_key(str(code))), styles["small"]),
                        Paragraph(_xml_text(str(escore)), styles["badge"]),
                    ]
                )
            cw = [page_width - 1.2 * inch, 1.2 * inch]
            ed_table = Table(ed_data, colWidths=cw, repeatRows=1)
            ed_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.HexColor("#F8F9FA"), colors.white],
                        ),
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BDC3C7")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            elements.append(ed_table)

    elements.append(Spacer(1, 0.15 * inch))
    elements.append(
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#BDC3C7"))
    )
    doc.build(elements)
    return buffer.getvalue()


def pdf_bytes_for_proposal_review(
    review: ProposalReview,
    *,
    document_title: str,
    editorial_feedback: dict | None = None,
) -> bytes:
    payload = merged_review_payload(
        review.result_data or {},
        review.overall_rating,
        review.overall_score_numeric,
        review.overall_rationale or None,
        review.overall_confidence,
    )
    return build_proposal_review_pdf_bytes(
        payload,
        document_title,
        editorial_feedback=editorial_feedback,
    )
