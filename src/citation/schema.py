from utils.openalex import OpenAlex
from utils.parsers import json_serial

from .constants import CITATION_TYPE_FIELDS, CREATOR_TYPES, JOURNAL_ARTICLE

# https://www.zotero.org/support/kb/item_types_and_fields

CREATOR_TYPE_FIELDS = set()
for creator_type in CREATOR_TYPES.values():
    for creator_type_field in creator_type:
        CREATOR_TYPE_FIELDS.add(creator_type_field)

initial_creators_schema_regex = r"|".join(f"^{field}$" for field in CREATOR_TYPE_FIELDS)
CREATORS_SCHEMA_REGEX = f"({initial_creators_schema_regex})"


def generate_json_for_doi_via_oa(doi):
    json_dict = {}
    schema = generate_schema_for_citation(JOURNAL_ARTICLE)
    open_alex = OpenAlex()
    result = open_alex.get_data_from_doi(doi)
    for field in schema["required"]:
        mapping_field = OPENALEX_JOURNAL_MAPPING.get(field, "")
        if mapping_field:
            if field == "creators":
                authors = result[mapping_field]
                author_array = []
                for author in authors:
                    name = author["author"]["display_name"]
                    if "," in name:
                        names = name.split(", ")
                        author_array.append(
                            {"first_name": names[1], "last_name": names[0]}
                        )
                    else:
                        names = name.split(" ")
                        author_array.append(
                            {"first_name": names[0], "last_name": names[len(names) - 1]}
                        )
                json_dict[field] = author_array
            else:
                pdf_value = mapping_field.split(".")
                cur_json = result
                for val in pdf_value:
                    cur_json = result[val]
                json_dict[field] = cur_json
        else:
            json_dict[field] = ""
    return json_dict


def generate_json_for_rh_paper(paper):
    json_dict = {}
    schema = generate_schema_for_citation(JOURNAL_ARTICLE)
    for field in schema["required"]:
        mapping_field = CITATION_TO_PAPER_MAPPING.get(field, "")
        if mapping_field:
            json_dict[field] = json_serial(
                getattr(paper, mapping_field, ""), ignore_errors=True
            )
        else:
            json_dict[field] = ""
    return json_dict


def generate_json_for_pdf(filename):
    json_dict = {}
    schema = generate_schema_for_citation(JOURNAL_ARTICLE)
    for key, value in schema["properties"].items():
        value_type = value["type"]
        if value_type == "string":
            json_dict[key] = ""
        elif value_type == "array":
            json_dict[key] = []
        elif value_type == "object":
            json_dict[key] = {}
        else:
            raise Exception("Unknown value type for schema")

    json_dict["title"] = filename
    return json_dict


def generate_schema_for_citation(citation_type):
    # creator_fields = CREATOR_TYPES[citation_type]
    # creators_schema_regex = r"|".join(f"^{field}$" for field in creator_fields)
    creators_schema = {
        # "type": "object",
        # "patternProperties": {
        #     f"{creators_schema_regex}": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["first_name", "last_name"],
        },
        #     }
        # },
        "minProperties": 1,
        "additionalProperties": False,
    }

    citation_fields = CITATION_TYPE_FIELDS[citation_type]
    citation_field_properties = {
        citation_field: CSL_SCHEMA["items"]["properties"].get(
            citation_field, {"type": "string"}
        )
        for citation_field in citation_fields
    }
    general_schema = {
        "type": "object",
        "properties": {
            "author": creators_schema,
            **citation_field_properties,
        },
        "required": ["author", *citation_fields],
        "additionalProperties": False,
    }
    return general_schema


# CREATORS_SCHEMA = {
#     "type": "object",
#     "patternProperties": {
#         f"{CREATORS_SCHEMA_REGEX}": {
#             "type": "array",
#             "items": {
#                 "type": "object",
#                 "properties": {
#                     "first_name": {"type": "string"},
#                     "last_name": {"type": "string"},
#                     "title": {"type": "string"},
#                 },
#                 "required": ["first_name", "last_name"],
#             },
#         }
#     },
#     "minProperties": 1,
#     "additionalProperties": False,
# }


# GENERAL_SCHEMA_FIELDS = [
#     "title",
#     "abstract",
#     "date",
#     "short_title",
#     "language",
#     "rights",
#     "date_added",
#     "date_modified",
#     "extra",
#     "creators",
# ]
# GENERAL_SCHEMA = {
#     "type": "object",
#     "properties": {
#         "title": {"type": "string"},
#         "abstract": {"type": "string"},
#         "date": {"type": "string"},
#         "short_title": {"type": "string"},
#         "language": {"type": "string"},
#         "rights": {"type": "string"},
#         "date_added": {"type": "string"},
#         "date_modified": {"type": "string"},
#         "extra": {"type": "string"},
#         "creators": CREATORS_SCHEMA,
#     },
#     "required": GENERAL_SCHEMA_FIELDS,
# }

# ACCESSED_SCHEMA_FIELDS = [
#     "accessed",
#     "url",
#     "archive",
#     "location_in_archive",
#     "library_catalog",
#     "call_number",
# ]
# ACCESSED_SCHEMA = {
#     "type": "object",
#     "properties": {
#         "accessed": {"type": "string"},
#         "doi": {"type": "string"},
#         "url": {"type": "string"},
#         "archive": {"type": "string"},
#         "location_in_archive": {"type": "string"},
#         "library_catalog": {"type": "string"},
#         "call_number": {"type": "string"},
#     },
# }

# BOOKS_AND_PERIODICALS_SCHEMA_FIELDS = [
#     "publication",
#     "volume",
#     "issue",
#     "pages",
#     "edition",
#     "series",
#     "series_number",
#     "series_title",
#     "section",
#     "place",
#     "publisher",
#     "journal_abbreviation",
#     "isbn",
#     "issn",
# ]
# BOOKS_AND_PERIODICALS_SCHEMA = {
#     "type": "object",
#     "properties": {
#         "publication": {"type": "string"},
#         "book_title": {"type": "string"},
#         "dictionary_title": {"type": "string"},
#         "encyclopedia_title": {"type": "string"},
#         "volume": {"type": "string"},
#         "issue": {"type": "string"},
#         "pages": {"type": "string"},
#         "edition": {"type": "string"},
#         "series": {"type": "string"},
#         "series_number": {"type": "string"},
#         "series_title": {"type": "string"},
#         "number_of_volumes": {"type": "string"},
#         "number_of_pages": {"type": "string"},
#         "section": {"type": "string"},
#         "place": {"type": "string"},
#         "publisher": {"type": "string"},
#         "journal_abbreviation": {"type": "string"},
#         "isbn": {"type": "string"},
#         "issn": {"type": "string"},
#     },
# }

# REPORTS_AND_THESES_SCHEMA_FIELDS = ["report_number", "instituion", "university"]
# REPORTS_AND_THESES_SCHEMA = {
#     "type": "object",
#     "properties": {
#         "type": {"type": "string"},
#         "report_type": {"type": "string"},
#         "report_number": {"type": "string"},
#         "instituion": {"type": "string"},
#         "university": {"type": "string"},
#     },
# }

# PRESENTATION_AND_PERFORMANCES_SCHEMA_FIELDS = ["proceedings_title", "place", "type"]
# PRESENTATION_AND_PERFORMANCES_SCHEMA = {
#     "type": "object",
#     "properties": {
#         "proceedings_title": {"type": "string"},
#         "conference_name": {"type": "string"},
#         "meeting_name": {"type": "string"},
#         "place": {"type": "string"},
#         "type": {"type": "string"},
#     },
# }

# RECORDING_AND_BROADCAST_SCHEMA_FIELDS = [
#     "running_time",
#     "program_title",
#     "episode_number",
#     "network",
#     "label",
#     "distributor",
#     "studio",
#     "genre",
# ]
# RECORDING_AND_BROADCAST_SCHEMA = {
#     "format": {"type": "string"},
#     "file_type": {"type": "string"},
#     "running_time": {"type": "string"},
#     "program_title": {"type": "string"},
#     "episode_number": {"type": "string"},
#     "network": {"type": "string"},
#     "label": {"type": "string"},
#     "distributor": {"type": "string"},
#     "studio": {"type": "string"},
#     "genre": {"type": "string"},
# }

# IMAGES_ARTWORK_MAPS_SCHEMA_FIELDS = ["medium", "artwork_size", "scale", "type"]
# IMAGES_ARTWORK_MAPS_SCHEMA = {
#     "medium": {"type": "string"},
#     "artwork_size": {"type": "string"},
#     "scale": {"type": "string"},
#     "type": {"type": "string"},
# }

# PRIMARY_SOURCES_AND_PERSONAL_COMMUNICATIONS_SCHEMA_FIELDS = [
#     "medium",
#     "type",
#     "subject",
# ]
# PRIMARY_SOURCES_AND_PERSONAL_COMMUNICATIONS_SCHEMA = {
#     "medium": {"type": "string"},
#     "type": {"type": "string"},
#     "subject": {"type": "string"},
# }

# WEBSITE_SCHEMA_FIELDS = ["website_type", "post_type"]
# WEBSITE_SCHEMA = {
#     "website_title": {"type": "string"},
#     "blog_title": {"type": "string"},
#     "forum/listserv_title": {"type": "string"},
#     "website_type": {"type": "string"},
#     "post_type": {"type": "string"},
# }

# SOFTWARE_SCHEMA_FIELDS = ["version", "system", "company", "language"]
# SOFTWARE_SCHEMA = {
#     "version": {"type": "string"},
#     "system": {"type": "string"},
#     "company": {"type": "string"},
#     "language": {"type": "string"},
# }

# LEGISLATION_AND_HEARINGS_SCHEMA_FIELDS = [
#     "name_of_act",
#     "bill_number",
#     "code",
#     "code_volume",
#     "code_number",
#     "public_law_number",
#     "date_enacted",
#     "section",
#     "committee",
#     "document_number",
#     "code_pages",
#     "legislative_body",
#     "session",
#     "history",
# ]
# LEGISLATION_AND_HEARINGS_SCHEMA = {
#     "name_of_act": {"type": "string"},
#     "bill_number": {"type": "string"},
#     "code": {"type": "string"},
#     "code_volume": {"type": "string"},
#     "code_number": {"type": "string"},
#     "public_law_number": {"type": "string"},
#     "date_enacted": {"type": "string"},
#     "section": {"type": "string"},
#     "committee": {"type": "string"},
#     "document_number": {"type": "string"},
#     "code_pages": {"type": "string"},
#     "legislative_body": {"type": "string"},
#     "session": {"type": "string"},
#     "history": {"type": "string"},
# }

# LEGAL_CASES_SCHEMA_FIELDS = [
#     "history",
#     "case_name",
#     "court",
#     "date_decided",
#     "docket_number",
#     "reporter",
#     "reporter_volume",
#     "first_page",
# ]
# LEGAL_CASES_SCHEMA = {
#     "history": {"type": "string"},
#     "case_name": {"type": "string"},
#     "court": {"type": "string"},
#     "date_decided": {"type": "string"},
#     "docket_number": {"type": "string"},
#     "reporter": {"type": "string"},
#     "reporter_volume": {"type": "string"},
#     "first_page": {"type": "string"},
# }

# PATENTS_SCHEMA_FIELDS = [
#     "country",
#     "assignee",
#     "issuing_authority",
#     "patent_number",
#     "filing_date",
#     "issue_date",
#     "application_number",
#     "priority_numbers",
#     "references",
#     "legal_status",
# ]

# PATENTS_SCHEMA = {
#     "country": {"type": "string"},
#     "assignee": {"type": "string"},
#     "issuing_authority": {"type": "string"},
#     "patent_number": {"type": "string"},
#     "filing_date": {"type": "string"},
#     "issue_date": {"type": "string"},
#     "application_number": {"type": "string"},
#     "priority_numbers": {"type": "string"},
#     "references": {"type": "string"},
#     "legal_status": {"type": "string"},
# }

CITATION_TO_PAPER_MAPPING = {
    "DOI": "doi",
    "creators": "raw_authors",
    "title": "paper_title",
    "date": "paper_publish_date",
    "abstract": "abstract",
    "publication_title": "paper_title",
    "journal_abbreviation": "external_source",
    "is_oa": "is_open_access",
    "url": "url",
}

OPENALEX_JOURNAL_MAPPING = {
    "DOI": "doi",
    "creators": "authorships",
    "title": "title",
    "date": "publication_date",
    "abstract": "abstract",
    "publication_title": "",
    "journal_abbreviation": "",
    "publication_type": "publication_type",
    "is_oa": "openaccess.is_oa",
}


# Taken from https://raw.githubusercontent.com/citation-style-language/schema/master/schemas/input/csl-data.json
CSL_SCHEMA = {
    "description": "JSON schema for CSL input data",
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "https://resource.citationstyles.org/schema/v1.0/input/json/csl-data.json",
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": [
                    "article",
                    "article-journal",
                    "article-magazine",
                    "article-newspaper",
                    "bill",
                    "book",
                    "broadcast",
                    "chapter",
                    "classic",
                    "collection",
                    "dataset",
                    "document",
                    "entry",
                    "entry-dictionary",
                    "entry-encyclopedia",
                    "event",
                    "figure",
                    "graphic",
                    "hearing",
                    "interview",
                    "legal_case",
                    "legislation",
                    "manuscript",
                    "map",
                    "motion_picture",
                    "musical_score",
                    "pamphlet",
                    "paper-conference",
                    "patent",
                    "performance",
                    "periodical",
                    "personal_communication",
                    "post",
                    "post-weblog",
                    "regulation",
                    "report",
                    "review",
                    "review-book",
                    "software",
                    "song",
                    "speech",
                    "standard",
                    "thesis",
                    "treaty",
                    "webpage",
                ],
            },
            "id": {"type": ["string", "number"]},
            "citation-key": {"type": "string"},
            "categories": {"type": "array", "items": {"type": "string"}},
            "language": {"type": "string"},
            "journalAbbreviation": {"type": "string"},
            "shortTitle": {"type": "string"},
            "author": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "chair": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "collection-editor": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "compiler": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "composer": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "container-author": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "contributor": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "curator": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "director": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "editor": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "editorial-director": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "executive-producer": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "guest": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "host": {"type": "array", "items": {"$ref": "#/definitions/name-variable"}},
            "interviewer": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "illustrator": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "narrator": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "organizer": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "original-author": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "performer": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "producer": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "recipient": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "reviewed-author": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "script-writer": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "series-creator": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "translator": {
                "type": "array",
                "items": {"$ref": "#/definitions/name-variable"},
            },
            "accessed": {"$ref": "#/definitions/date-variable"},
            "available-date": {"$ref": "#/definitions/date-variable"},
            "event-date": {"$ref": "#/definitions/date-variable"},
            "issued": {"$ref": "#/definitions/date-variable"},
            "original-date": {"$ref": "#/definitions/date-variable"},
            "submitted": {"$ref": "#/definitions/date-variable"},
            "abstract": {"type": "string"},
            "annote": {"type": "string"},
            "archive": {"type": "string"},
            "archive_collection": {"type": "string"},
            "archive_location": {"type": "string"},
            "archive-place": {"type": "string"},
            "authority": {"type": "string"},
            "call-number": {"type": "string"},
            "chapter-number": {"type": ["string", "number"]},
            "citation-number": {"type": ["string", "number"]},
            "citation-label": {"type": "string"},
            "collection-number": {"type": ["string", "number"]},
            "collection-title": {"type": "string"},
            "container-title": {"type": "string"},
            "container-title-short": {"type": "string"},
            "dimensions": {"type": "string"},
            "division": {"type": "string"},
            "DOI": {"type": "string"},
            "edition": {"type": ["string", "number"]},
            "event": {
                "description": "[Deprecated - use 'event-title' instead. Will be removed in 1.1]",
                "type": "string",
            },
            "event-title": {"type": "string"},
            "event-place": {"type": "string"},
            "first-reference-note-number": {"type": ["string", "number"]},
            "genre": {"type": "string"},
            "ISBN": {"type": "string"},
            "ISSN": {"type": "string"},
            "issue": {"type": ["string", "number"]},
            "jurisdiction": {"type": "string"},
            "keyword": {"type": "string"},
            "locator": {"type": ["string", "number"]},
            "medium": {"type": "string"},
            "note": {"type": "string"},
            "number": {"type": ["string", "number"]},
            "number-of-pages": {"type": ["string", "number"]},
            "number-of-volumes": {"type": ["string", "number"]},
            "original-publisher": {"type": "string"},
            "original-publisher-place": {"type": "string"},
            "original-title": {"type": "string"},
            "page": {"type": ["string", "number"]},
            "page-first": {"type": ["string", "number"]},
            "part": {"type": ["string", "number"]},
            "part-title": {"type": "string"},
            "PMCID": {"type": "string"},
            "PMID": {"type": "string"},
            "printing": {"type": ["string", "number"]},
            "publisher": {"type": "string"},
            "publisher-place": {"type": "string"},
            "references": {"type": "string"},
            "reviewed-genre": {"type": "string"},
            "reviewed-title": {"type": "string"},
            "scale": {"type": "string"},
            "section": {"type": "string"},
            "source": {"type": "string"},
            "status": {"type": "string"},
            "supplement": {"type": ["string", "number"]},
            "title": {"type": "string"},
            "title-short": {"type": "string"},
            "URL": {"type": "string"},
            "version": {"type": "string"},
            "volume": {"type": ["string", "number"]},
            "volume-title": {"type": "string"},
            "volume-title-short": {"type": "string"},
            "year-suffix": {"type": "string"},
            "custom": {
                "title": "Custom key-value pairs.",
                "type": "object",
                "description": "Used to store additional information that does not have a designated CSL JSON field. The custom field is preferred over the note field for storing custom data, particularly for storing key-value pairs, as the note field is used for user annotations in annotated bibliography styles.",
                "examples": [
                    {"short_id": "xyz", "other-ids": ["alternative-id"]},
                    {"metadata-double-checked": True},
                ],
            },
        },
        "required": ["type", "id"],
        "additionalProperties": False,
    },
    "definitions": {
        "name-variable": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "family": {"type": "string"},
                        "given": {"type": "string"},
                        "dropping-particle": {"type": "string"},
                        "non-dropping-particle": {"type": "string"},
                        "suffix": {"type": "string"},
                        "comma-suffix": {"type": ["string", "number", "boolean"]},
                        "static-ordering": {"type": ["string", "number", "boolean"]},
                        "literal": {"type": "string"},
                        "parse-names": {"type": ["string", "number", "boolean"]},
                    },
                    "additionalProperties": False,
                }
            ]
        },
        "date-variable": {
            "title": "Date content model.",
            "description": "The CSL input model supports two different date representations: an EDTF string (preferred), and a more structured alternative.",
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "date-parts": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {"type": ["string", "number"]},
                                "minItems": 1,
                                "maxItems": 3,
                            },
                            "minItems": 1,
                            "maxItems": 2,
                        },
                        "season": {"type": ["string", "number"]},
                        "circa": {"type": ["string", "number", "boolean"]},
                        "literal": {"type": "string"},
                        "raw": {"type": "string"},
                    },
                    "additionalProperties": False,
                }
            ],
        },
    },
}


ZOTERO_FIELDS_TO_CSL_MAPPING = {
    "abstract_note": "abstract",
    "archive": "archive",
    "archive_location": "archive_location",
    "authority": "authority",
    "call_number": "call-number",
    "application_number": "call-number",
    "session": "chapter-number",
    "series_number": "collection-number",
    "series_title": "collection-title",
    "series": "collection-title",
    "publication_title": "container-title",
    "reporter": "container-title",
    "code": "container-title",
    "artwork_size": "dimensions",
    "running_time": "dimensions",
    "DOI": "DOI",
    "edition": "edition",
    "place": "publisher-place",
    "meeting_name": "event-title",
    "conference_name": "event-title",
    "type": "genre",
    "programming_language": "genre",
    "ISBN": "ISBN",
    "ISSN": "ISSN",
    "issue": "issue",
    "priority_numbers": "issue",
    "journal_abbreviation": "journalAbbreviation",
    "language": "language",
    "rights": "license",
    "medium": "medium",
    "system": "medium",
    "extra": "note",
    "number": "number",
    "num_pages": "number-of-pages",
    "number_of_volumes": "number-of-volumes",
    "pages": "page",
    "publisher": "publisher",
    "history": "references",
    "references": "references",
    "scale": "scale",
    "section": "section",
    "committee": "section",
    "short_title": "title-short",
    "library_catalog": "source",
    "status": "status",
    "title": "title",
    "url": "URL",
    "version_number": "version",
    "volume": "volume",
    "code_number": "volume",
}

# CSL_TO_ZOTEORO_FIELDS_MAPPING = {list_itr: key for key, value in zotero_fields_to_csl.items() for list_itr in value}
