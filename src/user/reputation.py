from utils.openalex import OpenAlex


def calculate_g_index(orcid_id):
    open_alex = OpenAlex()
    sorted_citations = sorted(
        [work["cited_by_count"] for work in open_alex.get_author_works_data(orcid_id)],
        reverse=True,
    )
    cumulative_citations = 0
    for i, citations in enumerate(sorted_citations):
        cumulative_citations += citations
        if cumulative_citations < (i + 1) ** 2:
            return i
    return i + 1


def calculate_authorships(orcid_id):
    first_authorships, senior_authorships, supporting_authorships = 0, 0, 0
    open_alex = OpenAlex()
    works = open_alex.get_author_works_data(orcid_id)
    openalex_id = open_alex.get_author_data(orcid_id)["id"].split("/")[-1]
    for w in works:
        for a in w["authorships"]:
            if a["author"]["id"] == f"https://openalex.org/{openalex_id}":
                if a["author_position"] == "first":
                    first_authorships += 1
                if a["author_position"] == "last":
                    senior_authorships += 1
                if a["author_position"] == "middle":
                    supporting_authorships += 1
    return first_authorships, senior_authorships, supporting_authorships
