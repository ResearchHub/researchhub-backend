import os

from research_ai.constants import ExpertiseLevel, Gender, Region

# Descriptions for prompt building; keys are choice values from constants.
EXPERTISE_DESCRIPTIONS: dict[str, str] = {
    ExpertiseLevel.PHD_POSTDOCS: "Early-stage researchers including PhD students in their final years, recent PhD graduates, and current postdoctoral researchers. These individuals typically have 0-3 years of research experience and are building their expertise in specific areas.",
    ExpertiseLevel.EARLY_CAREER: "Researchers with 3-8 years of experience post-PhD, including Assistant Professors, Research Scientists, and Industry Researchers in their early career stages. They have established some independent research but are still developing their reputation.",
    ExpertiseLevel.MID_CAREER: "Established researchers with 8-15 years of experience, typically Associate Professors, Senior Scientists, or Principal Investigators who have significant publications and recognition in their field.",
    ExpertiseLevel.TOP_EXPERT: "Leading authorities in their field with 15+ years of experience, typically Full Professors, Distinguished Scientists, or Department Heads who are internationally recognized and have made significant contributions to their research areas.",
    ExpertiseLevel.ALL_LEVELS: "Include experts from all career stages, providing a diverse mix of perspectives and expertise levels.",
}

REGION_DESCRIPTIONS: dict[str, str] = {
    Region.US: "Focus exclusively on experts affiliated with institutions in the United States, including universities, research centers, and organizations based in the US.",
    Region.NON_US: "Focus exclusively on experts affiliated with institutions outside the United States, including international universities, research centers, and organizations worldwide.",
    Region.EUROPE: "Focus on experts affiliated with institutions in Europe, including countries such as United Kingdom, Germany, France, Italy, Spain, Netherlands, Switzerland, Sweden, Norway, Denmark, Belgium, Austria, Finland, Poland, Czech Republic, Ireland, Portugal, Greece, Russia, Ukraine, Belarus, Estonia, Latvia, Lithuania, and other European Union and non-EU European nations.",
    Region.ASIA_PACIFIC: "Focus on experts affiliated with institutions in the Asia-Pacific region, including countries such as China, Japan, South Korea, Australia, New Zealand, Singapore, India, Thailand, Malaysia, Indonesia, Philippines, Vietnam, Kazakhstan, Uzbekistan, Kyrgyzstan, Tajikistan, Turkmenistan, Mongolia, and other Asia-Pacific nations.",
    Region.AFRICA_MENA: "Focus on experts affiliated with institutions in Africa and the Middle East & North Africa (MENA) region, including countries in sub-Saharan Africa, North Africa, and the Middle East such as Egypt, South Africa, Nigeria, Kenya, UAE, Saudi Arabia, Israel, Turkey, Iran, Morocco, Tunisia, etc.",
    Region.ALL_REGIONS: "Include experts from all geographic regions worldwide, ensuring global diversity in recommendations.",
}

GENDER_DESCRIPTIONS: dict[str, str] = {
    Gender.MALE: "Focus on male-identifying experts and researchers in your recommendations.",
    Gender.FEMALE: "Focus on female-identifying experts and researchers in your recommendations.",
    Gender.ALL_GENDERS: "Include experts and researchers of all genders in your recommendations.",
}

_PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_template_cache: dict[str, str] = {}


def _load_template(name: str) -> str:
    """Load a prompt template from the prompts directory. Results are cached."""
    if name not in _template_cache:
        path = os.path.join(_PROMPTS_DIR, name)
        with open(path, encoding="utf-8") as f:
            _template_cache[name] = f.read()
    return _template_cache[name]


def get_prompt(prompt_name: str) -> str:
    """Retrieve a prompt template by name (unformatted)."""
    mapping = {
        "system_prompt": "expert_finder_system.txt",
        "user_query": "expert_finder_user_query.txt",
        "user_pdf": "expert_finder_user_pdf.txt",
    }
    filename = mapping.get(prompt_name.lower())
    return _load_template(filename) if filename else ""


def build_excluded_experts_instruction(excluded_expert_names: list[str]) -> str:
    """
    Build the optional paragraph instructing the model to exclude given experts.

    Used when the user runs multiple searches on the same document and wants
    different experts (exclude previously suggested names).

    Args:
        excluded_expert_names: List of full names to exclude.

    Returns:
        Instruction paragraph string, or empty string if list is empty.
    """
    if not excluded_expert_names:
        return ""
    names = "\n".join(f"- {name}" for name in excluded_expert_names)
    return (
        "\n\n## Exclude These Experts\n"
        "IMPORTANT: Please exclude the following experts from your search results, "
        "as they have been suggested in previous searches:\n"
        f"{names}\n"
        "Do NOT include any of the above names in your recommendations table."
    )


def _normalize_expertise_levels(expertise_level: list[str] | str) -> list[str]:
    """Normalize expertise_level to a flat list of strings (safe for dict lookups)."""
    if isinstance(expertise_level, str):
        return [expertise_level] if expertise_level else []
    if not expertise_level:
        return []
    flat = []
    for x in expertise_level:
        if isinstance(x, str):
            flat.append(x)
        elif isinstance(x, list):
            flat.extend(y for y in x if isinstance(y, str))
    return flat


def _expertise_levels_display(expertise_level: list[str] | str) -> str:
    """Normalize expertise_level to list and return display string."""
    levels = _normalize_expertise_levels(expertise_level)
    if not levels or (
        len(levels) == 1 and levels[0] == ExpertiseLevel.ALL_LEVELS
    ):
        return ExpertiseLevel.ALL_LEVELS
    return ", ".join(levels)


def build_system_prompt(
    expert_count: int,
    expertise_level: list[str] | str,
    region_filter: str,
    state_filter: str = "All States",
    gender_filter: str = "All Genders",
    excluded_expert_names: list[str] | None = None,
) -> str:
    """
    Build the complete system prompt with all configuration parameters.
    expertise_level: list of expertise level choices, or single string (legacy).
    """
    levels = _normalize_expertise_levels(expertise_level)
    expertise_instruction = ""
    if levels and not (
        len(levels) == 1 and levels[0] == ExpertiseLevel.ALL_LEVELS
    ):
        descriptions = []
        for level in levels:
            # level is guaranteed str from _normalize_expertise_levels
            desc = EXPERTISE_DESCRIPTIONS.get(level, level)
            descriptions.append(f"• {level}: {desc}")
        expertise_instruction = (
            "\n\n## Expertise Level Targeting\nFocus specifically on the following "
            "expertise level(s):\n" + "\n".join(descriptions)
        )

    region_instruction = ""
    if region_filter != Region.ALL_REGIONS:
        region_instruction = (
            f"\n\n## Geographic Region Targeting\nFocus specifically on {region_filter}: "
            f"{REGION_DESCRIPTIONS.get(region_filter, region_filter)}"
        )

    state_instruction = ""
    if region_filter == Region.US and state_filter != "All States":
        state_instruction = (
            f"\n\n## US State-Specific Targeting\n"
            f"Further narrow your search to experts affiliated with institutions "
            f"specifically in {state_filter}."
        )

    gender_instruction = ""
    if gender_filter != Gender.ALL_GENDERS:
        gender_instruction = (
            f"\n\n## Gender Preference Targeting\n"
            f"{GENDER_DESCRIPTIONS.get(gender_filter, gender_filter)}"
        )

    excluded_experts_instruction = build_excluded_experts_instruction(
        excluded_expert_names or []
    )

    template = _load_template("expert_finder_system.txt")
    expertise_level_display = _expertise_levels_display(expertise_level)
    return template.format(
        expert_count=expert_count,
        expertise_level=expertise_level_display,
        region_filter=region_filter,
        gender_filter=gender_filter,
        expertise_instruction=expertise_instruction,
        region_instruction=region_instruction,
        state_instruction=state_instruction,
        gender_instruction=gender_instruction,
        excluded_experts_instruction=excluded_experts_instruction,
    )


def build_user_prompt(
    query: str,
    expert_count: int,
    expertise_level: list[str] | str,
    region_filter: str,
    gender_filter: str = "All Genders",
    is_pdf: bool = False,
) -> str:
    """
    Build the user prompt for expert search.
    expertise_level: list of expertise level choices, or single string (legacy).
    """
    expertise_level_display = _expertise_levels_display(expertise_level)
    region_text = (
        "" if region_filter == Region.ALL_REGIONS else f" from the {region_filter} region"
    )
    if is_pdf:
        template = _load_template("expert_finder_user_pdf.txt")
        return template.format(
            query=query,
            expert_count=expert_count,
            expertise_level=expertise_level_display,
            region_text=region_text,
        )
    template = _load_template("expert_finder_user_query.txt")
    return template.format(
        query=query,
        expert_count=expert_count,
        expertise_level=expertise_level_display,
        region_text=region_text,
    )
