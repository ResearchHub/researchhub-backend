import decimal
from datetime import date, datetime

from django.utils.text import slugify
from rest_framework.parsers import BaseParser

ISO_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class PlainTextParser(BaseParser):
    """
    Plain text parser.
    """

    media_type = "text/plain"

    def parse(self, stream, media_type=None, parser_context=None):
        """
        Simply return a string representing the body of the request.
        """
        return stream.read()


def json_serial(obj, ignore_errors=False):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return str(obj)
    if obj is None:
        return ""
    if ignore_errors:
        return obj
    raise TypeError("Type %s not serializable" % type(obj))


def clean_filename(filename):
    filename_parts = filename.split(".")
    if len(filename_parts) > 1:
        extension = slugify(filename_parts[-1])
        return f"{slugify(filename_parts[0])}.{extension}"
    else:
        return slugify(filename)


def rebuild_sentence_from_inverted_index(index):
    if not isinstance(index, dict):
        return None

    reverse_index = {i: key for key, value in index.items() for i in value}
    sentence_array = [reverse_index[key] for key in sorted(reverse_index.keys())]
    return " ".join(sentence_array)
