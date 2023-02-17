from .constants import CITATION_TYPE_FIELDS, CREATOR_TYPES

# https://www.zotero.org/support/kb/item_types_and_fields

CREATOR_TYPE_FIELDS = set()
for creator_type in CREATOR_TYPES.values():
    for creator_type_field in creator_type:
        CREATOR_TYPE_FIELDS.add(creator_type_field)

initial_creators_schema_regex = r"|".join(f"^{field}$" for field in CREATOR_TYPE_FIELDS)
CREATORS_SCHEMA_REGEX = f"({initial_creators_schema_regex})"


def generate_schema_for_citation(citation_type):
    creator_fields = CREATOR_TYPES[citation_type]
    creators_schema_regex = r"|".join(f"^{field}$" for field in creator_fields)
    creators_schema = {
        "type": "object",
        "patternProperties": {
            f"{creators_schema_regex}": {
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
            }
        },
        "minProperties": 1,
        "additionalProperties": False,
    }

    citation_fields = CITATION_TYPE_FIELDS[citation_type]
    citation_field_properties = {
        citation_field: {"type": "string"} for citation_field in citation_fields
    }
    general_schema = {
        "type": "object",
        "properties": {"creators": creators_schema, **citation_field_properties},
        "required": ["creators", *citation_fields],
        "additionalProperties": False,
    }
    return general_schema


CREATORS_SCHEMA = {
    "type": "object",
    "patternProperties": {
        f"{CREATORS_SCHEMA_REGEX}": {
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
        }
    },
    "minProperties": 1,
    "additionalProperties": False,
}


GENERAL_SCHEMA_FIELDS = [
    "title",
    "abstract",
    "date",
    "short_title",
    "language",
    "rights",
    "date_added",
    "date_modified",
    "extra",
    "creators",
]
GENERAL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "abstract": {"type": "string"},
        "date": {"type": "string"},
        "short_title": {"type": "string"},
        "language": {"type": "string"},
        "rights": {"type": "string"},
        "date_added": {"type": "string"},
        "date_modified": {"type": "string"},
        "extra": {"type": "string"},
        "creators": CREATORS_SCHEMA,
    },
    "required": GENERAL_SCHEMA_FIELDS,
}

ACCESSED_SCHEMA_FIELDS = [
    "accessed",
    "url",
    "archive",
    "location_in_archive",
    "library_catalog",
    "call_number",
]
ACCESSED_SCHEMA = {
    "type": "object",
    "properties": {
        "accessed": {"type": "string"},
        "doi": {"type": "string"},
        "url": {"type": "string"},
        "archive": {"type": "string"},
        "location_in_archive": {"type": "string"},
        "library_catalog": {"type": "string"},
        "call_number": {"type": "string"},
    },
}

BOOKS_AND_PERIODICALS_SCHEMA_FIELDS = [
    "publication",
    "volume",
    "issue",
    "pages",
    "edition",
    "series",
    "series_number",
    "series_title",
    "section",
    "place",
    "publisher",
    "journal_abbreviation",
    "isbn",
    "issn",
]
BOOKS_AND_PERIODICALS_SCHEMA = {
    "type": "object",
    "properties": {
        "publication": {"type": "string"},
        "book_title": {"type": "string"},
        "dictionary_title": {"type": "string"},
        "encyclopedia_title": {"type": "string"},
        "volume": {"type": "string"},
        "issue": {"type": "string"},
        "pages": {"type": "string"},
        "edition": {"type": "string"},
        "series": {"type": "string"},
        "series_number": {"type": "string"},
        "series_title": {"type": "string"},
        "number_of_volumes": {"type": "string"},
        "number_of_pages": {"type": "string"},
        "section": {"type": "string"},
        "place": {"type": "string"},
        "publisher": {"type": "string"},
        "journal_abbreviation": {"type": "string"},
        "isbn": {"type": "string"},
        "issn": {"type": "string"},
    },
}

REPORTS_AND_THESES_SCHEMA_FIELDS = ["report_number", "instituion", "university"]
REPORTS_AND_THESES_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "report_type": {"type": "string"},
        "report_number": {"type": "string"},
        "instituion": {"type": "string"},
        "university": {"type": "string"},
    },
}

PRESENTATION_AND_PERFORMANCES_SCHEMA_FIELDS = ["proceedings_title", "place", "type"]
PRESENTATION_AND_PERFORMANCES_SCHEMA = {
    "type": "object",
    "properties": {
        "proceedings_title": {"type": "string"},
        "conference_name": {"type": "string"},
        "meeting_name": {"type": "string"},
        "place": {"type": "string"},
        "type": {"type": "string"},
    },
}

RECORDING_AND_BROADCAST_SCHEMA_FIELDS = [
    "running_time",
    "program_title",
    "episode_number",
    "network",
    "label",
    "distributor",
    "studio",
    "genre",
]
RECORDING_AND_BROADCAST_SCHEMA = {
    "format": {"type": "string"},
    "file_type": {"type": "string"},
    "running_time": {"type": "string"},
    "program_title": {"type": "string"},
    "episode_number": {"type": "string"},
    "network": {"type": "string"},
    "label": {"type": "string"},
    "distributor": {"type": "string"},
    "studio": {"type": "string"},
    "genre": {"type": "string"},
}

IMAGES_ARTWORK_MAPS_SCHEMA_FIELDS = ["medium", "artwork_size", "scale", "type"]
IMAGES_ARTWORK_MAPS_SCHEMA = {
    "medium": {"type": "string"},
    "artwork_size": {"type": "string"},
    "scale": {"type": "string"},
    "type": {"type": "string"},
}

PRIMARY_SOURCES_AND_PERSONAL_COMMUNICATIONS_SCHEMA_FIELDS = [
    "medium",
    "type",
    "subject",
]
PRIMARY_SOURCES_AND_PERSONAL_COMMUNICATIONS_SCHEMA = {
    "medium": {"type": "string"},
    "type": {"type": "string"},
    "subject": {"type": "string"},
}

WEBSITE_SCHEMA_FIELDS = ["website_type", "post_type"]
WEBSITE_SCHEMA = {
    "website_title": {"type": "string"},
    "blog_title": {"type": "string"},
    "forum/listserv_title": {"type": "string"},
    "website_type": {"type": "string"},
    "post_type": {"type": "string"},
}

SOFTWARE_SCHEMA_FIELDS = ["version", "system", "company", "language"]
SOFTWARE_SCHEMA = {
    "version": {"type": "string"},
    "system": {"type": "string"},
    "company": {"type": "string"},
    "language": {"type": "string"},
}

LEGISLATION_AND_HEARINGS_SCHEMA_FIELDS = [
    "name_of_act",
    "bill_number",
    "code",
    "code_volume",
    "code_number",
    "public_law_number",
    "date_enacted",
    "section",
    "committee",
    "document_number",
    "code_pages",
    "legislative_body",
    "session",
    "history",
]
LEGISLATION_AND_HEARINGS_SCHEMA = {
    "name_of_act": {"type": "string"},
    "bill_number": {"type": "string"},
    "code": {"type": "string"},
    "code_volume": {"type": "string"},
    "code_number": {"type": "string"},
    "public_law_number": {"type": "string"},
    "date_enacted": {"type": "string"},
    "section": {"type": "string"},
    "committee": {"type": "string"},
    "document_number": {"type": "string"},
    "code_pages": {"type": "string"},
    "legislative_body": {"type": "string"},
    "session": {"type": "string"},
    "history": {"type": "string"},
}

LEGAL_CASES_SCHEMA_FIELDS = [
    "history",
    "case_name",
    "court",
    "date_decided",
    "docket_number",
    "reporter",
    "reporter_volume",
    "first_page",
]
LEGAL_CASES_SCHEMA = {
    "history": {"type": "string"},
    "case_name": {"type": "string"},
    "court": {"type": "string"},
    "date_decided": {"type": "string"},
    "docket_number": {"type": "string"},
    "reporter": {"type": "string"},
    "reporter_volume": {"type": "string"},
    "first_page": {"type": "string"},
}

PATENTS_SCHEMA_FIELDS = [
    "country",
    "assignee",
    "issuing_authority",
    "patent_number",
    "filing_date",
    "issue_date",
    "application_number",
    "priority_numbers",
    "references",
    "legal_status",
]
PATENTS_SCHEMA = {
    "country": {"type": "string"},
    "assignee": {"type": "string"},
    "issuing_authority": {"type": "string"},
    "patent_number": {"type": "string"},
    "filing_date": {"type": "string"},
    "issue_date": {"type": "string"},
    "application_number": {"type": "string"},
    "priority_numbers": {"type": "string"},
    "references": {"type": "string"},
    "legal_status": {"type": "string"},
}


# new_fields = {}
# base_fields = {}
# creator_types = {}
# for item_type in z:
#     name = item_type.get("itemType")
#     fields = item_type.get("fields")
#     field_names = []
#     for field_name in fields:
#         field = field_name.get("field")
#         field_names.append(field)
#         if "baseField" in field_name:
#             base_fields[field] = field_name["baseField"]
#     creator_fields = item_type.get("creatorTypes", [])
#     creator_type_fields = []
#     for creator_field in creator_fields:
#         creator_field = creator_field.get("creatorType")
#         creator_type_fields.append(creator_field)
#     creator_types[name] = creator_type_fields
#     new_fields[name] = field_names

# validate({"artist": [{"first_name": "blah", "last_name": "test"}]}, schema=CREATORS_SCHEMA)
# validate({"creators": {"artist": [{"first_name": "blah", "last_name": "test"}]}, "title": "title", "abstract": "blah", "date": "1-1-11", "date_added": "1-1-11", "date_modified": "1-1-11", "short_title": "hmm", "language": "", "rights": "", "extra": ""}, schema=GENERAL_SCHEMA)
# validate({"creators": {"artist": []}, "title": "", "abstract": "", "date": "", "short_title": "", "language": ""}, schema=GENERAL_SCHEMA)
# validate({"performer": {'test': 1}}, schema=CREATORS_SCHEMA)
# validate({'blah': 1, "artist": {"artist": {"x": "x"}, "performer": {"x": "x"}}}, schema=CREATORS_SCHEMA)

# validate({"creators": {"artist": [{"first_name": "blah", "last_name": "test"}]}, "title": "title", "abstract": "blah", "date": "1-1-11", "date_added": "1-1-11", "date_modified": "1-1-11", "short_title": "hmm", "language": "", "rights": "", "extra": "", "abstract_note": "", "artwork_medium": "", "artwork_size": "", "archive": "", "archive_location": "", "library_catalog": "", "call_number": "", "url": "", "access_date": "1-1-11"}, schema=generate_schema_for_citation("ARTWORK"))
