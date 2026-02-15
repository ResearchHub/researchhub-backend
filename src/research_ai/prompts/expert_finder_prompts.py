import os

# Expertise level descriptions for targeting specific career stages
EXPERTISE_DESCRIPTIONS = {
    "PhD/PostDocs": "Early-stage researchers including PhD students in their final years, recent PhD graduates, and current postdoctoral researchers. These individuals typically have 0-3 years of research experience and are building their expertise in specific areas.",
    "Early Career Researchers": "Researchers with 3-8 years of experience post-PhD, including Assistant Professors, Research Scientists, and Industry Researchers in their early career stages. They have established some independent research but are still developing their reputation.",
    "Mid-Career Researchers": "Established researchers with 8-15 years of experience, typically Associate Professors, Senior Scientists, or Principal Investigators who have significant publications and recognition in their field.",
    "Top Expert/World Renowned Expert": "Leading authorities in their field with 15+ years of experience, typically Full Professors, Distinguished Scientists, or Department Heads who are internationally recognized and have made significant contributions to their research areas.",
    "All Levels": "Include experts from all career stages, providing a diverse mix of perspectives and expertise levels.",
}

# Geographic region descriptions for location-based filtering
REGION_DESCRIPTIONS = {
    "US": "Focus exclusively on experts affiliated with institutions in the United States, including universities, research centers, and organizations based in the US.",
    "non-US": "Focus exclusively on experts affiliated with institutions outside the United States, including international universities, research centers, and organizations worldwide.",
    "Europe": "Focus on experts affiliated with institutions in Europe, including countries such as United Kingdom, Germany, France, Italy, Spain, Netherlands, Switzerland, Sweden, Norway, Denmark, Belgium, Austria, Finland, Poland, Czech Republic, Ireland, Portugal, Greece, Russia, Ukraine, Belarus, Estonia, Latvia, Lithuania, and other European Union and non-EU European nations.",
    "Asia-Pacific": "Focus on experts affiliated with institutions in the Asia-Pacific region, including countries such as China, Japan, South Korea, Australia, New Zealand, Singapore, India, Thailand, Malaysia, Indonesia, Philippines, Vietnam, Kazakhstan, Uzbekistan, Kyrgyzstan, Tajikistan, Turkmenistan, Mongolia, and other Asia-Pacific nations.",
    "Africa & MENA": "Focus on experts affiliated with institutions in Africa and the Middle East & North Africa (MENA) region, including countries in sub-Saharan Africa, North Africa, and the Middle East such as Egypt, South Africa, Nigeria, Kenya, UAE, Saudi Arabia, Israel, Turkey, Iran, Morocco, Tunisia, etc.",
    "All Regions": "Include experts from all geographic regions worldwide, ensuring global diversity in recommendations.",
}

# Gender preference descriptions for gender-based filtering
GENDER_DESCRIPTIONS = {
    "Male": "Focus on male-identifying experts and researchers in your recommendations.",
    "Female": "Focus on female-identifying experts and researchers in your recommendations.",
    "All Genders": "Include experts and researchers of all genders in your recommendations.",
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


def build_system_prompt(
    expert_count: int,
    expertise_level: str,
    region_filter: str,
    state_filter: str = "All States",
    gender_filter: str = "All Genders",
    excluded_expert_names: list[str] | None = None,
) -> str:
    """
    Build the complete system prompt with all configuration parameters.
    """
    expertise_instruction = ""
    if expertise_level != "All Levels":
        expertise_instruction = (
            f"\n\n## Expertise Level Targeting\nFocus specifically on {expertise_level}: "
            f"{EXPERTISE_DESCRIPTIONS.get(expertise_level, expertise_level)}"
        )

    region_instruction = ""
    if region_filter != "All Regions":
        region_instruction = (
            f"\n\n## Geographic Region Targeting\nFocus specifically on {region_filter}: "
            f"{REGION_DESCRIPTIONS.get(region_filter, region_filter)}"
        )

    state_instruction = ""
    if region_filter == "US" and state_filter != "All States":
        state_instruction = (
            f"\n\n## US State-Specific Targeting\n"
            f"Further narrow your search to experts affiliated with institutions "
            f"specifically in {state_filter}."
        )

    gender_instruction = ""
    if gender_filter != "All Genders":
        gender_instruction = (
            f"\n\n## Gender Preference Targeting\n"
            f"{GENDER_DESCRIPTIONS.get(gender_filter, gender_filter)}"
        )

    excluded_experts_instruction = build_excluded_experts_instruction(
        excluded_expert_names or []
    )

    template = _load_template("expert_finder_system.txt")
    return template.format(
        expert_count=expert_count,
        expertise_level=expertise_level,
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
    expertise_level: str,
    region_filter: str,
    gender_filter: str = "All Genders",
    is_pdf: bool = False,
) -> str:
    """
    Build the user prompt for expert search.
    """
    region_text = (
        "" if region_filter == "All Regions" else f" from the {region_filter} region"
    )
    if is_pdf:
        template = _load_template("expert_finder_user_pdf.txt")
        return template.format(
            expert_count=expert_count,
            expertise_level=expertise_level,
            region_text=region_text,
        )
    template = _load_template("expert_finder_user_query.txt")
    return template.format(
        query=query,
        expert_count=expert_count,
        expertise_level=expertise_level,
        region_text=region_text,
    )
