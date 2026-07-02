"""Judge-facing context compaction.

Judges score RFP fit, budget fit, credibility, and novelty, so they need the
grant's terms, the researcher's real record, and the draft's citations -- but
compacted, so the rubric prompt is not swamped by full call text or full
abstracts. These are pure data-shaping helpers: the draft runner supplies the
raw context and the size caps, and ``build_judge_context`` assembles the
evidence bundle both the ``judge_proposal`` tool and the panel gate pass to
``ProposalJudgePanel``.
"""


def trim_context_text(value: object, max_chars: int) -> str:
    """Trim long context strings without cutting mid-word when practical."""
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rsplit(" ", 1)[0].rstrip()
    return (trimmed or text[:max_chars]).rstrip() + "..."


def compact_rfp_context(rfp_ctx: dict, *, max_chars: int) -> dict:
    """Small judge-facing RFP context: structured terms plus trimmed call text."""
    rfp_ctx = rfp_ctx if isinstance(rfp_ctx, dict) else {}
    out = {
        "organization": rfp_ctx.get("organization"),
        "short_title": rfp_ctx.get("short_title"),
        "amount": rfp_ctx.get("amount"),
        "currency": rfp_ctx.get("currency"),
        "end_date": rfp_ctx.get("end_date"),
    }
    if rfp_ctx.get("error"):
        out["error"] = rfp_ctx["error"]
    rfp_text = trim_context_text(rfp_ctx.get("rfp_text"), max_chars)
    if rfp_text:
        out["rfp_text"] = rfp_text
    return {k: v for k, v in out.items() if v not in (None, "")}


def compact_profile_context(
    profile: dict,
    *,
    max_works: int,
    max_abstract_chars: int,
) -> dict:
    """Small judge-facing researcher profile for credibility/novelty scoring."""
    profile = profile if isinstance(profile, dict) else {}
    raw_resolution = profile.get("resolution")
    resolution = raw_resolution if isinstance(raw_resolution, dict) else {}
    works = []
    for work in profile.get("works") or []:
        if not isinstance(work, dict):
            continue
        compact = {
            "title": work.get("title"),
            "publication_year": work.get("publication_year"),
            "source_url": work.get("source_url"),
            "author_position": work.get("author_position"),
            "abstract": trim_context_text(
                work.get("abstract"),
                max_abstract_chars,
            ),
        }
        works.append({k: v for k, v in compact.items() if v not in (None, "")})
        if len(works) >= max_works:
            break
    return {
        "resolution": {
            k: v
            for k, v in resolution.items()
            if k
            in (
                "openalex_author_id",
                "display_name",
                "orcid",
                "confidence",
                "reasoning",
            )
            and v not in (None, "")
        },
        "works": works,
        "errors": profile.get("errors") or [],
    }


def compact_citations(citations: object) -> list[dict]:
    """Judge-facing structured citations from a submit/tool-call payload."""
    out = []
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        compact = {
            "claim_id": citation.get("claim_id"),
            "doi": citation.get("doi"),
            "source_url": citation.get("source_url"),
            "title": citation.get("title"),
            "authors": citation.get("authors") or [],
        }
        out.append({k: v for k, v in compact.items() if v not in (None, "", [])})
    return out


def build_judge_context(
    *,
    rfp_context: dict,
    profile: dict,
    citations: object,
    grounded_urls: set[str],
    max_rfp_chars: int,
    max_works: int,
    max_abstract_chars: int,
) -> dict:
    """Evidence judges need for RFP fit, budget fit, credibility, and novelty."""
    return {
        "rfp": compact_rfp_context(rfp_context, max_chars=max_rfp_chars),
        "researcher_profile": compact_profile_context(
            profile,
            max_works=max_works,
            max_abstract_chars=max_abstract_chars,
        ),
        "citations": compact_citations(citations),
        "grounded_source_urls": sorted(grounded_urls),
    }
