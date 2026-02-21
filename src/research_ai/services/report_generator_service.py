import csv
import io
import logging
from typing import Any
from xml.sax.saxutils import escape

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from research_ai.constants import ExpertiseLevel, Region, get_choice_label

logger = logging.getLogger(__name__)


def generate_pdf_report(
    experts: list[dict[str, Any]],
    query: str,
    config: dict[str, Any],
) -> bytes:
    """
    Create a PDF report of expert recommendations using ReportLab.

    Args:
        experts: List of expert dicts (name, title, affiliation, expertise, email).
        query: Original search query.
        config: Search configuration (expert_count, expertise_level, region, state).

    Returns:
        PDF file content as bytes.
    """
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5 * inch)
        styles = getSampleStyleSheet()
        elements = []

        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Title"],
            fontSize=18,
            textColor=colors.HexColor("#4E29A9"),
            spaceAfter=20,
        )
        elements.append(Paragraph("Expert Finder Recommendations", title_style))
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(
            Paragraph(
                f"<b>Recommended Experts ({len(experts)} found):</b>",
                styles["Heading2"],
            )
        )
        elements.append(Spacer(1, 0.1 * inch))

        text_style = ParagraphStyle(
            "Justified",
            parent=styles["Normal"],
            fontSize=10,
            leading=12,
        )

        for i, expert in enumerate(experts, 1):
            card_data = [
                [
                    Paragraph(
                        f"<b>{i}. {escape(expert.get('name', ''))}</b>",
                        text_style,
                    )
                ],
                [
                    Paragraph(
                        f"<b>Title:</b> {escape(expert.get('title', ''))}",
                        text_style,
                    )
                ],
                [
                    Paragraph(
                        f"<b>Affiliation:</b> {escape(expert.get('affiliation', ''))}",
                        text_style,
                    )
                ],
                [
                    Paragraph(
                        f"<b>Expertise:</b> {escape(expert.get('expertise', ''))}",
                        text_style,
                    )
                ],
                [
                    Paragraph(
                        f"<b>Email:</b> {escape(expert.get('email', ''))}",
                        text_style,
                    )
                ],
                [
                    Paragraph(
                        f"<b>Notes:</b> {escape(expert.get('notes', ''))}",
                        text_style,
                    )
                ],
            ]
            card_table = Table(card_data, colWidths=[6.5 * inch])
            card_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0EBFF")),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#4E29A9")),
                    ]
                )
            )
            elements.append(card_table)
            elements.append(Spacer(1, 0.15 * inch))

        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph("<b>Research Query:</b>", styles["Heading3"]))
        query_text = escape(query[:500] + "..." if len(query) > 500 else query)
        elements.append(Paragraph(query_text, styles["Normal"]))
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("<b>Search Configuration:</b>", styles["Heading3"]))
        expert_count = config.get("expert_count", config.get("expertCount", 10))
        expertise_level_raw = config.get(
            "expertise_level", config.get("expertiseLevel", [ExpertiseLevel.ALL_LEVELS])
        )
        if isinstance(expertise_level_raw, list):
            expertise_level = (
                ", ".join(get_choice_label(v, ExpertiseLevel) for v in expertise_level_raw)
                if expertise_level_raw
                else ExpertiseLevel.ALL_LEVELS.label
            )
        else:
            expertise_level = get_choice_label(
                expertise_level_raw or ExpertiseLevel.ALL_LEVELS,
                ExpertiseLevel,
            )
        region_val = config.get("region", Region.ALL_REGIONS)
        region = get_choice_label(region_val, Region)
        state = config.get("state", "All States")
        config_text = (
            f"• Expert Count: {expert_count}<br/>"
            f"• Expertise Level: {expertise_level}<br/>"
            f"• Geographic Region: {region}<br/>"
            f"• State: {state}"
        )
        elements.append(Paragraph(config_text, styles["Normal"]))
        elements.append(Spacer(1, 0.3 * inch))

        footer_style = ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.grey,
            alignment=1,
        )
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(
            Paragraph(
                "Research AI Expert Finder by ResearchHub © 2025.",
                footer_style,
            )
        )

        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        logger.info("PDF report generated successfully")
        return pdf_bytes
    except Exception as e:
        logger.exception("Failed to generate PDF report: %s", e)
        return b"%PDF-1.4\nError generating PDF report\n%%EOF"


def generate_csv_file(experts: list[dict[str, Any]]) -> bytes:
    """
    Create a CSV file of expert recommendations.

    Args:
        experts: List of expert dicts.

    Returns:
        CSV file content as bytes (UTF-8).
    """
    try:
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=["name", "title", "affiliation", "expertise", "email", "notes"],
        )
        writer.writeheader()
        for expert in experts:
            writer.writerow(
                {
                    "name": expert.get("name", ""),
                    "title": expert.get("title", ""),
                    "affiliation": expert.get("affiliation", ""),
                    "expertise": expert.get("expertise", ""),
                    "email": expert.get("email", ""),
                    "notes": expert.get("notes", ""),
                }
            )
        csv_content = buffer.getvalue()
        buffer.close()
        csv_bytes = csv_content.encode("utf-8")
        logger.info("CSV file generated: %s bytes", len(csv_bytes))
        return csv_bytes
    except Exception as e:
        logger.exception("Failed to generate CSV file: %s", e)
        raise


def upload_report_to_storage(
    search_id: str,
    file_content: bytes,
    file_extension: str,
    content_type: str,
) -> str:
    """
    Upload a report file (PDF or CSV) to default storage (S3) and return its URL.

    Args:
        search_id: ExpertSearch UUID string.
        file_content: Raw file bytes.
        file_extension: "pdf" or "csv".
        content_type: MIME type (e.g. "application/pdf", "text/csv").

    Returns:
        Public URL of the uploaded file.
    """
    file_key = f"research_ai/expert-finder/{search_id}/report.{file_extension}"
    default_storage.save(file_key, ContentFile(file_content))
    url = default_storage.url(file_key)
    logger.info("Uploaded %s to %s", file_extension.upper(), file_key)
    return url
