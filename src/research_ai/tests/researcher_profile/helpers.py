"""Shared factories for the researcher_profile test modules."""

from types import SimpleNamespace


def make_expert(**kwargs):
    """Duck-typed Expert stand-in (no DB) for the pure-logic paths."""
    defaults = {
        "first_name": "Jane",
        "middle_name": "",
        "last_name": "Doe",
        "affiliation": "",
        "expertise": "",
        "sources": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def oa_author_record(**overrides):
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


def oa_work(title, year, position, author_id="https://openalex.org/A123"):
    slug = title.lower().replace(" ", "-")
    return {
        "display_name": title,
        "publication_year": year,
        "doi": f"https://doi.org/10.1/{slug}",
        "id": f"https://openalex.org/W-{slug}",
        "authorships": [{"author": {"id": author_id}, "author_position": position}],
    }
