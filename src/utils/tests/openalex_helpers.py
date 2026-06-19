"""Shared factories for building OpenAlex API payloads in tests."""


def create_oa_author_record(**overrides):
    record = {
        "id": "https://openalex.org/A123",
        "display_name": "Jane Doe",
        "display_name_alternatives": [],
        "orcid": "https://orcid.org/0000-0002-1825-0097",
        "summary_stats": {"h_index": 12, "i10_index": 5, "2yr_mean_citedness": 2.1},
        "works_count": 40,
        "cited_by_count": 900,
        "affiliations": [{"institution": {"display_name": "Stanford University"}}],
        "topics": [{"display_name": "Genomics"}, {"display_name": "Bioinformatics"}],
    }
    record.update(overrides)
    return record


def create_oa_work(
    title,
    year,
    position,
    author_id="https://openalex.org/A123",
    pdf_url=None,
    version="publishedVersion",
    is_oa=True,
):
    slug = title.lower().replace(" ", "-")
    if pdf_url is None:
        pdf_url = f"https://example.org/{slug}.pdf"
    # ``year`` is expanded to a Jan-1 ISO date; ``None`` means undated.
    publication_date = f"{year}-01-01" if year is not None else None
    return {
        "display_name": title,
        "publication_date": publication_date,
        "publication_year": year,
        "doi": f"https://doi.org/10.1/{slug}",
        "id": f"https://openalex.org/W-{slug}",
        "authorships": [{"author": {"id": author_id}, "author_position": position}],
        "primary_location": {"pdf_url": pdf_url, "version": version},
        "open_access": {"is_oa": is_oa},
    }
