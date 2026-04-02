import io
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

from ai_peer_review.constants import DIMENSION_KEYS, DIMENSION_SUB_AREAS

COLOR_HIGH = colors.HexColor("#27AE60")
COLOR_MEDIUM = colors.HexColor("#F39C12")
COLOR_LOW = colors.HexColor("#E74C3C")
COLOR_NA = colors.HexColor("#95A5A6")
COLOR_MAJOR_ROW = colors.HexColor("#FADBD8")
COLOR_MODERATE_ROW = colors.HexColor("#FEF9E7")
COLOR_MINOR_ROW = colors.white
COLOR_TABLE_HEADER = colors.HexColor("#6F42C1")

DIMENSION_LABELS = {
    "fundability": "Fundability",
    "feasibility": "Feasibility",
    "novelty": "Novelty",
    "impact": "Impact",
    "reproducibility": "Reproducibility",
}

SUB_AREA_LABELS = {
    "scope_alignment": "Scope Alignment",
    "budget_adequacy": "Budget Adequacy",
    "timeline_realism": "Timeline Realism",
    "investigator_expertise": "Investigator Expertise",
    "institutional_capacity": "Institutional Capacity",
    "track_record": "Track Record (Optional)",
    "conceptual_novelty": "Conceptual Novelty",
    "methodological_novelty": "Methodological Novelty",
    "literature_positioning": "Literature Positioning",
    "scientific_impact": "Scientific Impact",
    "clinical_translational_impact": "Clinical / Translational (Optional)",
    "societal_broader_impact": "Societal & Broader Impact",
    "community_ecosystem_impact": "Community & Ecosystem (Optional)",
    "methods_rigor": "Methods Rigor",
    "statistical_analysis_plan": "Statistical Analysis Plan",
    "data_code_transparency": "Data & Code Transparency",
    "gold_standard_methodology": "Gold Standard Methodology (Optional)",
    "validation_robustness": "Validation & Robustness",
}


def _xml_text(text: object) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    return escape(s).replace("\n", "<br/>")


def _score_color(score: object) -> colors.Color:
    if score is None:
        return COLOR_NA
    s = str(score).strip().lower()
    if s in ("high", "excellent"):
        return COLOR_HIGH
    if s in ("medium", "good"):
        return COLOR_MEDIUM
    if s in ("low", "poor"):
        return COLOR_LOW
    if s == "n/a":
        return COLOR_NA
    return COLOR_NA


def merged_review_payload(
    result_data: dict,
    overall_rating: str | None,
    overall_score_numeric: int | None,
) -> dict:
    data = dict(result_data or {})
    if overall_rating is not None:
        data["overall_rating"] = overall_rating
    if overall_score_numeric is not None:
        data["overall_score_numeric"] = overall_score_numeric
    return data


def build_proposal_review_pdf_bytes(review_dict: dict, document_title: str) -> bytes:
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
        author="ResearchHub Foundation",
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
        "center": ParagraphStyle(
            "center",
            parent=base_styles["Normal"],
            fontSize=9,
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
            _xml_text(
                f"Generated by ResearchHub Foundation | {safe_title}",
            ),
            styles["subtitle"],
        )
    )

    elements += section_header("Section A - Editorial Summary")
    es = review_dict.get("editorial_summary") or {}
    overall_rating = review_dict.get("overall_rating", "N/A")
    overall_score = review_dict.get("overall_score_numeric", "N/A")
    consensus = es.get("consensus_summary", "")
    rating_color = _score_color(overall_rating)
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
                    f'<font color="#7F8C8D">({or_score}/15)</font>',
                    styles["bold"],
                ),
                Paragraph("", styles["normal"]),
            ]
        ],
        colWidths=[1.4 * inch, page_width - 1.4 * inch],
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
    elements.append(Spacer(1, 0.08 * inch))
    if consensus:
        elements.append(Paragraph("<b>Consensus Summary</b>", styles["sub_heading"]))
        elements.append(Paragraph(_xml_text(consensus), styles["normal"]))
        elements.append(Spacer(1, 0.08 * inch))

    action_items = es.get("priority_action_items") or []
    if action_items:
        elements.append(
            Paragraph("<b>Priority Action Items</b>", styles["sub_heading"])
        )
        for i, item in enumerate(action_items, 1):
            sev = item.get("severity", "")
            sev_color = (
                "#E74C3C"
                if sev == "Major"
                else ("#F39C12" if sev == "Moderate" else "#7F8C8D")
            )
            desc = _xml_text(item.get("description", ""))
            fix = _xml_text(item.get("suggested_fix", ""))
            pri = _xml_text(item.get("priority", ""))
            elements.append(
                Paragraph(
                    f'{i}. <font color="{sev_color}"><b>{_xml_text(sev)}</b></font> '
                    f"{desc}  "
                    f'<font color="#7F8C8D">- {fix}  [{pri}]</font>',
                    styles["normal"],
                )
            )
        elements.append(Spacer(1, 0.05 * inch))

    elements += section_header("Section B - Dimension Assessments")
    for dim_key in DIMENSION_KEYS:
        dim_label = DIMENSION_LABELS[dim_key]
        dim = review_dict.get(dim_key) or {}
        dim_score = dim.get("overall_score", "N/A")
        dim_rationale = dim.get("overall_rationale", "")
        dim_color = _score_color(dim_score)
        dim_hex = "#{:02X}{:02X}{:02X}".format(
            int(dim_color.red * 255),
            int(dim_color.green * 255),
            int(dim_color.blue * 255),
        )
        elements.append(
            Paragraph(
                f"<b>{_xml_text(dim_label)}</b>  "
                f'<font color="{dim_hex}">| {_xml_text(dim_score)}</font>',
                styles["sub_heading"],
            )
        )
        elements.append(Paragraph(_xml_text(dim_rationale), styles["small"]))
        elements.append(Spacer(1, 0.04 * inch))

        sub_area_keys = DIMENSION_SUB_AREAS.get(dim_key, [])
        table_data = [
            [
                Paragraph("Sub-Area", styles["table_header"]),
                Paragraph("Score", styles["table_header_center"]),
                Paragraph("Key Finding", styles["table_header"]),
            ]
        ]
        for sa_key in sub_area_keys:
            sa = dim.get(sa_key) or {}
            sa_score = sa.get("score", "N/A")
            sa_label = SUB_AREA_LABELS.get(sa_key, sa_key.replace("_", " ").title())
            sa_rationale = sa.get("rationale", "")
            sa_flags = sa.get("flags") or []
            flag_text = ""
            if sa_flags:
                flag_text = " Flags: " + "; ".join(str(x) for x in sa_flags)
            sa_color = _score_color(sa_score)
            sa_hex = "#{:02X}{:02X}{:02X}".format(
                int(sa_color.red * 255),
                int(sa_color.green * 255),
                int(sa_color.blue * 255),
            )
            table_data.append(
                [
                    Paragraph(_xml_text(sa_label), styles["small"]),
                    Paragraph(
                        f'<font color="{sa_hex}"><b>{_xml_text(sa_score)}</b></font>',
                        styles["badge"],
                    ),
                    Paragraph(_xml_text(sa_rationale + flag_text), styles["small"]),
                ]
            )
        col_widths = [1.7 * inch, 0.7 * inch, page_width - 2.4 * inch]
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

    elements += section_header("Section C - Feasibility & Timeline Check")
    tl = review_dict.get("feasibility_timeline_notes") or {}
    if tl:
        ms = tl.get("milestone_assessment", "")
        gng = tl.get("go_no_go_criteria", "")
        res_flags = tl.get("resource_flags") or []
        if ms:
            elements.append(
                Paragraph("<b>Milestone Assessment</b>", styles["sub_heading"])
            )
            elements.append(Paragraph(_xml_text(ms), styles["normal"]))
        if gng:
            elements.append(Spacer(1, 0.05 * inch))
            elements.append(
                Paragraph("<b>Go / No-Go Criteria</b>", styles["sub_heading"])
            )
            elements.append(Paragraph(_xml_text(gng), styles["normal"]))
        if res_flags:
            elements.append(Spacer(1, 0.05 * inch))
            elements.append(
                Paragraph("<b>Resource Adequacy Flags</b>", styles["sub_heading"])
            )
            for flag in res_flags:
                elements.append(Paragraph(_xml_text(f"- {flag}"), styles["normal"]))
    else:
        elements.append(Paragraph("No timeline notes available.", styles["normal"]))
    elements.append(Spacer(1, 0.05 * inch))

    elements += section_header("Section D - Budget Analysis")
    bn = review_dict.get("budget_notes") or {}
    if bn:
        li_flags = bn.get("line_item_flags") or []
        adj = bn.get("recommended_adjustments") or []
        if li_flags:
            elements.append(Paragraph("<b>Line Item Flags</b>", styles["sub_heading"]))
            for flag in li_flags:
                elements.append(Paragraph(_xml_text(f"- {flag}"), styles["normal"]))
            elements.append(Spacer(1, 0.05 * inch))
        if adj:
            elements.append(
                Paragraph("<b>Recommended Adjustments</b>", styles["sub_heading"])
            )
            adj_data = [
                [
                    Paragraph("Line Item", styles["table_header"]),
                    Paragraph("Proposed", styles["table_header"]),
                    Paragraph("Recommended", styles["table_header"]),
                    Paragraph("Rationale", styles["table_header"]),
                ]
            ]
            for row in adj:
                adj_data.append(
                    [
                        Paragraph(_xml_text(row.get("line_item", "")), styles["small"]),
                        Paragraph(_xml_text(row.get("proposed", "")), styles["small"]),
                        Paragraph(
                            _xml_text(row.get("recommended", "")), styles["small"]
                        ),
                        Paragraph(_xml_text(row.get("rationale", "")), styles["small"]),
                    ]
                )
            cw = [1.4 * inch, 1.0 * inch, 1.1 * inch, page_width - 3.5 * inch]
            adj_table = Table(adj_data, colWidths=cw, repeatRows=1)
            adj_table.setStyle(
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
            elements.append(adj_table)
    else:
        elements.append(Paragraph("No budget analysis available.", styles["normal"]))
    elements.append(Spacer(1, 0.05 * inch))

    elements += section_header("Section E - Issue Table")
    issue_table_data = review_dict.get("issue_table") or []
    if issue_table_data:
        table_rows = [
            [
                Paragraph("Severity", styles["table_header"]),
                Paragraph("Category", styles["table_header"]),
                Paragraph("Issue", styles["table_header"]),
                Paragraph("Suggested Fix", styles["table_header"]),
                Paragraph("Priority", styles["table_header"]),
            ]
        ]
        row_colors = []
        for entry in issue_table_data:
            sev = entry.get("severity", "")
            row_colors.append(
                COLOR_MAJOR_ROW
                if sev == "Major"
                else (COLOR_MODERATE_ROW if sev == "Moderate" else COLOR_MINOR_ROW)
            )
            sev_color = (
                "#E74C3C"
                if sev == "Major"
                else ("#F39C12" if sev == "Moderate" else "#7F8C8D")
            )
            table_rows.append(
                [
                    Paragraph(
                        f'<font color="{sev_color}"><b>{_xml_text(sev)}</b></font>',
                        styles["small"],
                    ),
                    Paragraph(_xml_text(entry.get("category", "")), styles["small"]),
                    Paragraph(_xml_text(entry.get("issue", "")), styles["small"]),
                    Paragraph(
                        _xml_text(entry.get("suggested_fix", "")), styles["small"]
                    ),
                    Paragraph(_xml_text(entry.get("priority", "")), styles["small"]),
                ]
            )
        cw = [0.7 * inch, 0.9 * inch, 1.7 * inch, 1.7 * inch, 0.7 * inch]
        issue_tbl = Table(table_rows, colWidths=cw, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BDC3C7")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i, clr in enumerate(row_colors, start=1):
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), clr))
        issue_tbl.setStyle(TableStyle(style_cmds))
        elements.append(issue_tbl)
    else:
        elements.append(Paragraph("No issues identified.", styles["normal"]))

    elements.append(Spacer(1, 0.15 * inch))
    elements.append(
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#BDC3C7"))
    )
    elements.append(
        Paragraph(
            "<font color='#7F8C8D' size='7'>"
            "Generated by ResearchHub Foundation | dev@researchhub.foundation</font>",
            styles["center"],
        )
    )
    doc.build(elements)
    return buffer.getvalue()
