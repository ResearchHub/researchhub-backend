import re

from utils.openalex import OpenAlex
from utils.parsers import json_serial

from .constants import CITATION_TYPE_FIELDS, JOURNAL_ARTICLE

# https://www.zotero.org/support/kb/item_types_and_fields


def date_string_to_parts(date):
    return re.split(r"[-,\.]", date)


def generate_json_for_doi_via_oa(doi):
    json_dict = {}
    schema = generate_schema_for_citation(JOURNAL_ARTICLE)
    open_alex = OpenAlex()
    result = open_alex.get_data_from_doi(doi)
    for field in schema["required"]:
        mapping_field = OPENALEX_JOURNAL_MAPPING.get(field, "")
        if mapping_field:
            if field == "author":
                authors = result[mapping_field]
                author_array = []
                for author in authors:
                    name = author["author"]["display_name"]
                    if "," in name:
                        names = name.split(", ")
                        author_array.append({"given": names[1], "family": names[0]})
                    else:
                        names = name.split(" ")
                        author_array.append(
                            {"given": names[0], "family": names[len(names) - 1]}
                        )
                json_dict[field] = author_array
            elif field == "issued":
                json_dict[field] = {
                    "date-parts": [date_string_to_parts(result[mapping_field])]
                }
            else:
                pdf_value = mapping_field.split(".")
                cur_json = result
                for val in pdf_value:
                    cur_json = result.get(val, "")
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
            author_array = []
            if mapping_field == "raw_authors":
                authors = getattr(paper, mapping_field)
                if authors:
                    for author in authors:
                        author_array.append(
                            {
                                "given": author.get("first_name", ""),
                                "family": author.get("last_name", ""),
                            }
                        )
                json_dict[field] = author_array
            elif mapping_field == "paper_publish_date":
                date_parts = {}
                publish_date = getattr(paper, mapping_field)
                if publish_date:
                    date_parts = {
                        "date-parts": [date_string_to_parts(publish_date.isoformat())]
                    }
                json_dict[field] = date_parts
            else:
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
        if "type" in value:
            value_type = value["type"]
            if value_type == "string":
                json_dict[key] = ""
            elif value_type == "array":
                json_dict[key] = []
            elif value_type == "object":
                json_dict[key] = {}
            elif isinstance(value_type, list):
                json_dict[key] = ""
        elif key == "author":
            json_dict[key] = []
        else:
            json_dict[key] = {}

    json_dict["title"] = filename
    return json_dict


def generate_schema_for_citation(citation_type):
    citation_fields = CITATION_TYPE_FIELDS[citation_type]
    citation_field_properties = {
        citation_field: CSL_SCHEMA["items"]["properties"].get(
            citation_field, {"type": "string"}
        )
        for citation_field in citation_fields
    }
    citation_field_properties["issued"] = CSL_SCHEMA["definitions"]["date-variable"]
    general_schema = {
        "type": "object",
        "properties": {
            "author": CSL_SCHEMA["definitions"]["name-variable"],
            **citation_field_properties,
        },
        "required": ["author", *citation_fields],
        "additionalProperties": False,
    }
    return general_schema


CITATION_TO_PAPER_MAPPING = {
    "DOI": "doi",
    "author": "raw_authors",
    "title": "paper_title",
    "issued": "paper_publish_date",
    "abstract": "abstract",
    "container-title": "paper_title",
    "journalAbbreviation": "external_source",
    "url": "url",
}

OPENALEX_JOURNAL_MAPPING = {
    "DOI": "doi",
    "ISSN": "issn_l",
    "author": "authorships",
    "title": "title",
    "issued": "publication_date",
    "abstract_inverted_index": "abstract",
    "container-title": "",
    "journalAbbreviation": "",
}

OPENALEX_TO_CSL_FORMAT = {
    "publication_date": "issued",
    "abstract_inverted_index": "abstract",
    "abstract": "abstract",
    "landing_page_url": "url",
    "primary_location": {
        "source": {
            "display_name": "source",
            "issn_l": "issn_l",
        }
    },
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
