from opensearchpy import Q

from utils.doi import DOI


class UnifiedSearchQueryBuilder:

    def build_document_query(self, query: str) -> Q:

        # Strategy A: Strict phrase matches with small slop (favor best field)
        phrase_strict = Q(
            "dis_max",
            queries=[
                Q(
                    "match_phrase",
                    paper_title={"query": query, "slop": 1, "boost": 3.0},
                ),
                Q("match_phrase", title={"query": query, "slop": 1, "boost": 3.0}),
                Q("match_phrase", abstract={"query": query, "slop": 2, "boost": 1.5}),
            ],
            tie_breaker=0.1,
        )

        # Strategy B: Phrase prefix allows partial last term in title
        phrase_prefix = Q(
            "dis_max",
            queries=[
                Q(
                    "match_phrase_prefix",
                    paper_title={"query": query, "max_expansions": 20, "boost": 2.5},
                ),
                Q(
                    "match_phrase_prefix",
                    title={"query": query, "max_expansions": 20, "boost": 2.5},
                ),
            ],
            tie_breaker=0.1,
        )

        # Strategy C: Fuzzy AND to handle typos across major fields (including authors)
        typo_and = Q(
            "multi_match",
            query=query,
            fields=[
                "paper_title^4",
                "title^4",
                "abstract^2",
                "renderable_text",
                "raw_authors.full_name^2",
                "authors.full_name^2",
            ],
            type="best_fields",
            fuzziness="AUTO",
            operator="and",
        )

        # Strategy D: Author + Title combo must co-occur
        author_title_combo = Q(
            "constant_score",
            filter=Q(
                "bool",
                must=[
                    Q(
                        "multi_match",
                        query=query,
                        type="cross_fields",
                        operator="or",
                        fields=["raw_authors.full_name^3", "authors.full_name^3"],
                    ),
                    Q(
                        "multi_match",
                        query=query,
                        type="best_fields",
                        operator="and",
                        fields=["paper_title^5", "title^5"],
                    ),
                ],
            ),
            boost=4.0,
        )

        shoulds = [
            author_title_combo,
            phrase_strict,
            phrase_prefix,
            typo_and,
        ]

        # Optional: direct DOI exact match if the query is a DOI
        try:
            if DOI.is_doi(query):
                normalized_doi = DOI.normalize_doi(query)
                shoulds.insert(
                    0,
                    Q("term", doi={"value": normalized_doi, "boost": 8.0}),
                )
        except Exception:
            pass

        return Q("bool", should=shoulds, minimum_should_match=1)

    def build_person_query(self, query: str) -> Q:

        return Q(
            "multi_match",
            query=query,
            fields=[
                "full_name^5",  # Highest boost for full name
                "first_name^3",
                "last_name^3",
                "headline^2",
                "description^1",
            ],
            type="best_fields",
            fuzziness="AUTO",
            operator="or",
        )

    def build_rescore_query(self, query: str) -> dict:

        return {
            "window_size": 100,
            "query": {
                "rescore_query": {
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "type": "cross_fields",
                                    "fields": [
                                        "raw_authors.full_name^2",
                                        "authors.full_name^2",
                                    ],
                                }
                            },
                            {
                                "multi_match": {
                                    "query": query,
                                    "type": "best_fields",
                                    "fields": ["paper_title^3", "title^3"],
                                }
                            },
                        ]
                    }
                },
                "query_weight": 0.9,
                "rescore_query_weight": 0.1,
            },
        }
