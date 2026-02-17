"""
Email generation prompts for expert outreach.
Ported from expertfinder generate-expert-email route; anti-hallucination preserved.
"""

BASE_RULES = """
CRITICAL RULES - DO NOT VIOLATE:
1. NEVER mention or reference any specific publications, papers, or studies
   unless they are explicitly provided in the expertise/notes fields
2. NEVER use superlatives or overstated language like: "groundbreaking",
   "seminal", "instrumental", "pioneering", "revolutionary", "world-class"
3. ONLY reference information that is explicitly provided about the expert
4. Keep tone conversational and authentic - avoid overly formal or flowery
5. DO NOT claim the expert has done work they haven't based on your training
6. If you don't know something from the provided information, don't mention it
7. Focus on shared interest/expertise rather than praising expert's past work
""".strip()

COMMON_INSTRUCTIONS = """
Generate a professional email (150-200 words max) to contact this expert.

{base_rules}

Format:
Subject: [subject line]

[Email body - keep it natural and genuine]

[Leave space for sender's signature]
""".strip()


def build_email_prompt(
    expert_name: str,
    expert_title: str,
    expert_affiliation: str,
    expertise: str,
    notes: str,
    template: str,
    custom_use_case: str | None = None,
) -> str:
    """
    Build the full user prompt for email generation.

    template: one of collaboration, consultation, conference, peer-review,
              publication, rfp-outreach, or custom (use custom_use_case for custom).
    """
    sender_info = f"""Expert Name: {expert_name or 'N/A'}
Title: {expert_title or 'N/A'}
Affiliation: {expert_affiliation or 'N/A'}
Expertise: {expertise or 'N/A'}
Additional Context: {notes or 'N/A'}"""

    common = COMMON_INSTRUCTIONS.format(base_rules=BASE_RULES)

    if template == "custom" and custom_use_case:
        return f"""{sender_info}

Use Case: {custom_use_case}

{common}

For this custom request, generate an email that authentically conveys the
stated use case without fabricating details about the expert's work."""

    if template == "collaboration":
        return f"""{sender_info}

{common}

For a collaboration opportunity:
- Express genuine interest in their expertise area (based only on what's provided)
- Briefly describe your research/work without exaggeration
- Propose a specific collaboration idea
- Keep it friendly and low-pressure
- Avoid praising their past work; focus on shared interests"""

    if template == "consultation":
        return f"""{sender_info}

{common}

For requesting expert consultation:
- Explain the specific challenge or question you're facing
- Connect it to their stated expertise area
- Be humble and specific about what advice you're seeking
- Avoid flattery or overstating their knowledge
- Focus on the problem, not on the expert"""

    if template == "conference":
        return f"""{sender_info}

{common}

For a conference or speaking invitation:
- Mention the specific event, conference, or symposium
- Briefly describe why their expertise is relevant
- Explain what audience would benefit from their participation
- Keep the invitation clear and specific
- Avoid phrases about their "renowned" or "celebrated" work"""

    if template == "peer-review":
        return f"""{sender_info}

{common}

For requesting peer review:
- Clearly state what needs review (manuscript, proposal, etc.)
- Explain why their expertise is relevant to evaluate the work
- Be clear about timeline and expectations
- Show respect for their time
- Avoid assuming they have reviewed similar work before"""

    if template == "publication":
        return f"""{sender_info}

{common}

For inviting a publication contribution:
- Specify the journal, book, or publication venue
- Explain the scope/theme of the publication
- Describe why their expertise fits this publication
- Be specific about what type of contribution is needed
- Avoid referencing any specific papers they may have written"""

    if template == "rfp-outreach":
        return f"""{sender_info}

{common}

For a Request for Proposal (RFP) outreach:
- Start with: "Dear [Researcher Name], My name is [Name] and I am an editor
  at [Your Organization/Institution Name]."
- Clearly mention the RFP topic/focus area and why it matches their expertise
- Explain why their expertise aligns with the RFP requirements
- Include placeholders: funding amount [e.g., $XXXXX], deadline [e.g., date]
- Keep it professional and straightforward
- Focus on the opportunity fit, not on praising their past achievements
- End with space for sender's signature and contact details
- Make it easy for them to show interest or ask questions"""

    # Default: general collaboration-style outreach
    return f"""{sender_info}

{common}

Generate a general professional outreach email based on this expert's expertise."""
