from research_ai.constants import (
    ExpertiseLevel,
    Region,
)
from research_ai.prompts._loader import load_template

PROFILE_MATCH_SYSTEM_PROMPT = load_template(
    "expert_finder_profile_match_system.txt"
).strip()

# Descriptions for prompt building; keys are choice values from constants.
EXPERTISE_DESCRIPTIONS: dict[str, str] = {
    ExpertiseLevel.PHD_POSTDOCS: "Early-stage researchers including PhD students in their final years, recent PhD graduates, and current postdoctoral researchers. These individuals typically have 0-3 years of research experience and are building their expertise in specific areas.",  # noqa: E501
    ExpertiseLevel.EARLY_CAREER: "Researchers with 3-8 years of experience post-PhD, including Assistant Professors, Research Scientists, and Industry Researchers in their early career stages. They have established some independent research but are still developing their reputation.",  # noqa: E501
    ExpertiseLevel.MID_CAREER: "Established researchers with 8-15 years of experience, typically Associate Professors, Senior Scientists, or Principal Investigators who have significant publications and recognition in their field.",  # noqa: E501
    ExpertiseLevel.TOP_EXPERT: "Leading authorities in their field with 15+ years of experience, typically Full Professors, Distinguished Scientists, or Department Heads who are internationally recognized and have made significant contributions to their research areas.",  # noqa: E501
    ExpertiseLevel.ALL_LEVELS: "Include experts from all career stages, providing a diverse mix of perspectives and expertise levels.",  # noqa: E501
}

REGION_DESCRIPTIONS: dict[str, str] = {
    Region.US: "Focus exclusively on experts affiliated with institutions in the United States, including universities, research centers, and organizations based in the US.",  # noqa: E501
    Region.NON_US: "Focus exclusively on experts affiliated with institutions outside the United States, including international universities, research centers, and organizations worldwide.",  # noqa: E501
    Region.EUROPE: "Focus on experts affiliated with institutions in Europe, including countries such as United Kingdom, Germany, France, Italy, Spain, Netherlands, Switzerland, Sweden, Norway, Denmark, Belgium, Austria, Finland, Poland, Czech Republic, Ireland, Portugal, Greece, Russia, Ukraine, Belarus, Estonia, Latvia, Lithuania, and other European Union and non-EU European nations.",  # noqa: E501
    Region.ASIA_PACIFIC: "Focus on experts affiliated with institutions in the Asia-Pacific region, including countries such as China, Japan, South Korea, Australia, New Zealand, Singapore, India, Thailand, Malaysia, Indonesia, Philippines, Vietnam, Kazakhstan, Uzbekistan, Kyrgyzstan, Tajikistan, Turkmenistan, Mongolia, and other Asia-Pacific nations.",  # noqa: E501
    Region.AFRICA_MENA: "Focus on experts affiliated with institutions in Africa and the Middle East & North Africa (MENA) region, including countries in sub-Saharan Africa, North Africa, and the Middle East such as Egypt, South Africa, Nigeria, Kenya, UAE, Saudi Arabia, Israel, Turkey, Iran, Morocco, Tunisia, etc.",  # noqa: E501
    Region.ALL_REGIONS: "Include experts from all geographic regions worldwide, ensuring global diversity in recommendations.",  # noqa: E501
}


def build_excluded_experts_instruction(excluded_expert_names: list[str]) -> str:
    """
    Build the optional paragraph instructing the model to exclude given experts.

    Used when running multiple searches on the same document and prior experts
    should not be suggested again.

    Args:
        excluded_expert_names: List of full names to exclude.

    Returns:
        Instruction paragraph string, or empty string if list is empty.
    """
    if not excluded_expert_names:
        return ""
    names = "\n".join(f"- {name}" for name in excluded_expert_names)
    return (
        "\n\n## Exclude These Experts - CRITICAL\n"
        "The following experts have already been suggested in previous searches. "
        "You MUST recommend a completely DIFFERENT set of experts.\n"
        f"{names}\n"
        "Your recommendations table must contain ONLY new experts who are NOT in the "
        "list above. "
        "Do NOT list the excluded experts in your table. "
        "Search for and recommend other qualified experts in the same field who are "
        "not listed above."
    )


def format_additional_context_section(additional_context: str | None) -> str:
    """
    Markdown block inserted after the main query/paper body in the user prompt.
    """
    stripped = (additional_context or "").strip()
    if not stripped:
        return ""
    return f"\n\n## Additional guidance from the requester\n{stripped}\n"


def build_profile_match_user_prompt(
    *,
    expert_name: str,
    academic_title: str = "",
    affiliation: str = "",
    expertise: str = "",
    email: str = "",
    notes: str = "",
    profile_kind: str,
    candidates: list[dict],
) -> str:
    """Build the user prompt for Bedrock social-profile matching."""
    lines: list[str] = []
    for i, row in enumerate(candidates or [], start=1):
        title = str((row or {}).get("title") or "").strip() or "(no title)"
        url = str((row or {}).get("url") or "").strip() or "(no url)"
        description = (
            str((row or {}).get("description") or "").strip() or "(no snippet)"
        )
        lines.append(f"{i}. title: {title}\n   url: {url}\n   snippet: {description}")
    candidates_block = "\n".join(lines) if lines else "(no candidates)"
    template = load_template("expert_finder_profile_match_user.txt")
    return template.format(
        expert_name=expert_name or "(unknown)",
        academic_title=academic_title or "(unknown)",
        affiliation=affiliation or "(unknown)",
        expertise=expertise or "(unknown)",
        email=email or "(unknown)",
        notes=notes or "(none)",
        profile_kind=profile_kind,
        candidates_block=candidates_block,
    )
