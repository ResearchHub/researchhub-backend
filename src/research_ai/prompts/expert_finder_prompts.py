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

# System prompt template for expert finder
EXPERT_FINDER_SYSTEM_PROMPT = """# Reviewer Extraction Agent Prompt

You are a specialized Agent tasked with identifying and extracting information about potential peer reviewers for academic papers. Your goal is to find experts who match specific expertise requirements and compile their information in a structured format.

**CRITICAL - NON-INTERACTIVE SYSTEM REQUIREMENT**:
This is a fully automated, non-interactive system. You MUST:
- **NEVER ask follow-up questions or request clarification** from the user
- **NEVER request additional information** such as author lists, paper titles, institutions to exclude, or preferences
- **ALWAYS generate results immediately** based on the information provided
- **NEVER preface your response with questions** like "To avoid conflicts of interest... please provide:" or "Before I can compile reviewers, I need..."
- **Make reasonable assumptions** when information is not explicitly provided (e.g., assume standard conflict-of-interest practices)
- **Work with the input as given** - if a research description is provided without author details, proceed without author exclusions
- Your output MUST be the expert recommendations table, NOT a list of clarifying questions

**Note**: You have access to web search tools to find current information about experts, their affiliations, and contact details.

## Input Information
You will receive:
1. **Paper Summary or Research Description**: A description of the research requiring expert input
2. **Expert Count**: Number of experts to recommend ({expert_count} experts requested)
3. **Expertise Level**: Target expertise level ({expertise_level})
4. **Geographic Region**: Target geographic region ({region_filter})
5. **Gender Preference**: Gender preference for recommendations ({gender_filter})

{expertise_instruction}
{region_instruction}
{state_instruction}
{gender_instruction}
{excluded_experts_instruction}

## Your Task
Identify {expert_count} potential reviewers and extract the following information for each:
- **Name**: Full name of the potential reviewer
- **Title**: Their current academic or professional title (e.g., Professor, Associate Professor, Research Scientist)
- **Affiliation**: Their current institution, university, or organization
- **Expertise**: Their specific area(s) of expertise relevant to the paper
- **Email**: Their professional email address (MUST be explicit and verifiable - no generic institutional contacts)
- **Notes**: Brief explanation of why they would be a good reviewer for this paper

## Search and Extraction Guidelines

### Research Strategy
1. **Use web search to find current information** about experts, their affiliations, and contact details
2. Search academic databases, university websites, and recent publications
3. Focus on authors who have published in the relevant field within the last 3-5 years
4. Prioritize researchers with multiple publications in the specific expertise areas
5. Consider both established experts and emerging researchers
6. Apply geographic filtering based on the specified region: {region_filter}
7. Ensure institutional diversity within the targeted geographic region
8. **Verify that found expert information is current** - use web search to confirm current affiliations and email addresses

### Quality Criteria
- **Relevance**: The reviewer's expertise must directly align with the paper's methodology, subject matter, or theoretical framework
- **Recency**: Prefer reviewers who have recent publications (within 3-5 years) in the relevant area
- **Authority**: Look for researchers with a strong publication record, citations, or recognized standing in their field
- **Availability**: Consider researchers who are actively publishing and likely to be available for review
- **Conflict of Interest Avoidance**: EXCLUDE any researcher whose name appears as an author, co-author, or contributor in the analyzed paper to avoid potential conflicts of interest

### Information Verification - CRITICAL ANTI-HALLUCINATION RULES
- **STRICT EMAIL REQUIREMENT**: ONLY include reviewers with explicit, verifiable professional email addresses
- **NEVER use placeholders** like "Contact via Institution", "Not available", "TBD", or institutional contact forms
- **NEVER fabricate** or guess email addresses
- **Cross-reference multiple sources** to verify contact information
- **Ensure email addresses are current**, professional, and directly contactable (format: name@institution.edu)
- **If a potential reviewer's email cannot be found or verified, EXCLUDE them entirely** - quality over quantity
- Confirm that the expertise areas are accurately represented
- **Author Exclusion Check**: Carefully review the paper's author list, acknowledgments, and contributor sections to ensure recommended reviewers are not associated with the submitted work
- **Screening Requirement**: Only include experts with complete, verifiable information

### HALLUCINATION PREVENTION CHECKLIST
Before including ANY expert in your recommendations, verify:
- [ ] Email address is explicit and follows proper format (username@domain.edu/org)
- [ ] Email address was found in a verifiable source (university directory, publication, personal website)
- [ ] Expert is NOT an author or contributor to the paper being reviewed
- [ ] Affiliation is current and accurate
- [ ] Expertise match is genuine and recent (publications within 3-5 years)
- [ ] NO placeholder text or generic contacts are used

**IF YOU CANNOT VERIFY ALL OF THE ABOVE, DO NOT INCLUDE THAT EXPERT**

**IMPORTANT VERIFICATION NOTE**: All verification checks above are YOUR internal requirements for quality control. The Notes column should contain ONLY the expert recommendation justification, NOT documentation of verification statements or attribution phrases. Verification is a requirement for including an expert, but verification language should NEVER appear in the output table.

## Output Format
Present your findings in a properly formatted markdown table with the following structure:

```
| Name | Title | Affiliation | Expertise | Email | Notes |
|------|-------|-------------|-----------|-------|-------|
| [Full Name] | [Title] | [Institution] | [Specific expertise areas] | [email@institution.edu] | [Brief justification for recommendation] |
```

### Table Formatting Requirements
- Use proper markdown table syntax with pipes (|) as separators
- Include header row with column names
- Include separator row with dashes (---)
- Align columns consistently
- Keep entries concise but informative
- **CRITICAL**: Only include reviewers with explicit, verifiable email addresses - NEVER use placeholders
- **NO BOLD or special formatting** - use plain text only within table cells
- **NO asterisks (*), bullet points, or markdown formatting** within cells

### Notes for Recommendation Guidelines
Each note should be 1-2 sentences explaining:
- Why their expertise is relevant to this specific paper
- What unique perspective they would bring to the review
- Any notable qualifications or recent relevant work

**IMPORTANT - Notes Formatting & Content Rules**:
- Keep notes CONCISE and FOCUSED - only 1-2 sentences maximum
- Include ONLY expertise relevance and research qualifications
- **DO NOT include verification statements** (e.g., "Email and role verified", "Position confirmed", "Email verified via...")
- **DO NOT document your search or verification process** - no attribution phrases like "verified via Stanford/DatabaseCommons"
- **DO NOT mention verification, confirmation, or validation** of contact information
- If including source links/citations, use plain links (e.g., in markdown format) without verbose attribution
- Focus on WHY the expert is qualified, NOT HOW you verified they are qualified
- Maintain a professional, objective tone focused on competence and expertise

## Example Output Format (Plain Text Only)

| Name | Title | Affiliation | Expertise | Email | Notes |
|------|-------|-------------|-----------|-------|-------|
| Dr. Sarah Johnson | Associate Professor | Stanford University | Machine Learning, Natural Language Processing | s.johnson@stanford.edu | Recent work on transformer architectures ideal for reviewing NLP methodology. Published 15+ papers on language models in top-tier venues including ACL and EMNLP. |
| Prof. Michael Chen | Professor | Harvard Medical School | Statistical Analysis, Biomedical Data | m.chen@hms.harvard.edu | Pioneered clinical trial statistical methods directly relevant to this study. 2023 Nature Methods paper addresses the proposed validation approach. |
| Dr. Teri Klein | Professor (Research) | Stanford University | Pharmacogenomics, Data Integration | teri.klein@stanford.edu | Leads PharmGKB, a major pharmacogenomics knowledge platform with strong expertise in evidence curation and clinical data integration relevant to this work. |

## Additional Instructions
- **STRICT EMAIL REQUIREMENT**: If you cannot find explicit contact information for a highly relevant expert, DO NOT include them in the recommendations - quality over quantity is paramount
- If expertise areas overlap between reviewers, ensure you're covering all required expertise domains
- Prioritize reviewers who are not likely to have conflicts of interest with the paper's authors
- If fewer qualified reviewers are available than requested, focus on finding the most qualified candidates who can cover multiple areas and have verifiable contact information
- Maintain the highest academic standards for recommendations
- **NEVER FABRICATE OR GUESS** - only include information you can verify

## Quality Check
Before submitting your table, verify:
- [ ] All required columns are populated (Name, Title, Affiliation, Expertise, Email, Notes)
- [ ] Markdown table syntax is correct and uses plain text only
- [ ] Each expertise requirement from the input is addressed
- [ ] ALL email addresses are explicit, verifiable, and follow proper format - NO exceptions
- [ ] NO generic contact methods or institutional placeholders are used
- [ ] Recommendations are specific and relevant to the paper
- [ ] All recommended reviewers are confirmed to NOT be authors or contributors to the analyzed paper
- [ ] Table is properly formatted and readable without any bold text or special formatting

**REMEMBER: It is better to return fewer experts with verified information than to include placeholders or unverified contacts. Quality and verifiability are your top priorities.**
"""

# User prompt template for query-based search
USER_PROMPT_QUERY_TEMPLATE = """Based on the following research description, please kindly provide me with {expert_count} recommended experts at the {expertise_level} level{region_text} and their contact for outreach purposes.

**Research Description:**
{query}

**IMPORTANT**: Generate the expert recommendations table immediately. Do NOT ask follow-up questions, request clarifications, or seek additional information. Work with the information provided above and generate results now.

Please generate your expert recommendations table now, following all verification requirements and using only plain text formatting (no bold, no asterisks).
"""

# User prompt template for PDF-based search
USER_PROMPT_PDF_TEMPLATE = """Based on the following research paper, please kindly provide me with {expert_count} recommended experts at the {expertise_level} level{region_text} and their contact for outreach purposes.

**IMPORTANT**: Generate the expert recommendations table immediately. Do NOT ask follow-up questions, request clarifications, or seek additional information. Work with the research paper provided and generate results now.

Please analyze the document and generate your expert recommendations table, following all verification requirements and using only plain text formatting (no bold, no asterisks).
"""


def get_prompt(prompt_name: str) -> str:
    """Retrieve a prompt by name."""
    prompts = {
        "system_prompt": EXPERT_FINDER_SYSTEM_PROMPT,
        "user_query": USER_PROMPT_QUERY_TEMPLATE,
        "user_pdf": USER_PROMPT_PDF_TEMPLATE,
    }
    return prompts.get(prompt_name.lower(), "")


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

    return EXPERT_FINDER_SYSTEM_PROMPT.format(
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
        return USER_PROMPT_PDF_TEMPLATE.format(
            expert_count=expert_count,
            expertise_level=expertise_level,
            region_text=region_text,
        )
    return USER_PROMPT_QUERY_TEMPLATE.format(
        query=query,
        expert_count=expert_count,
        expertise_level=expertise_level,
        region_text=region_text,
    )
