from django.core.management.base import BaseCommand
from jsonschema import Draft7Validator, validators

from citation.constants import ZOTERO_TO_CSL_MAPPING
from citation.models import CitationEntry
from citation.schema import CSL_SCHEMA


def extend_validator(validator_class):
    validate_properties = validator_class.VALIDATORS["properties"]

    def remove_additional_properties(validator, properties, instance, schema):
        for prop in list(instance.keys()):
            if prop not in properties:
                del instance[prop]

        for error in validate_properties(
            validator,
            properties,
            instance,
            schema,
        ):
            yield error

    return validators.extend(
        validator_class,
        {"properties": remove_additional_properties},
    )


Validator = extend_validator(Draft7Validator)


class Command(BaseCommand):
    def handle(self, *args, **options):
        validator = Validator(CSL_SCHEMA)

        for citation in CitationEntry.objects.all().iterator():
            fields = citation.fields
            if "creators" in fields:
                creators = fields["creators"]
                new_authors = []
                for creator in creators:
                    new_authors.append(
                        {"given": creator["first_name"], "family": creator["last_name"]}
                    )
                fields["author"] = new_authors

            if "date" in fields:
                date = fields["date"]
                date_parts = {"date-parts": [date.split("-")]}
                fields["issued"] = date_parts

            fields["type"] = ZOTERO_TO_CSL_MAPPING[citation.citation_type]
            fields["id"] = f"user_{citation.created_by.id}_{citation.citation_type}"
            validator.validate([fields])
            citation.fields = fields
            citation.save()
