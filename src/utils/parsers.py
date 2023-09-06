import decimal
from datetime import date, datetime

from django.utils import timezone
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


def dict_to_tuple(obj):
    return [(key, obj[key]) for key in obj]


def get_class_attributes(cls):
    attributes = {}
    for attribute in cls.__dict__.keys():
        if attribute[:2] != "__":
            value = getattr(cls, attribute)
            if not callable(value):
                attributes[attribute] = value
    return attributes


def iso_string_to_datetime(string, naive=False):
    """
    Returns a timezone aware datetime object in UTC based on `string`.

    `string` must represent a UTC date time such as `2011-10-05T14:48:00.000Z`

    Arguments:
        string (str)
        naive (:bool:) -- if True, a naive datetime object is returned
    """
    dt = timezone.datetime.strptime(string, ISO_DATE_FORMAT)
    if naive is True:
        return dt
    return timezone.make_aware(dt)


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


def get_pure_doi(doi_string):
    return doi_string.split("doi.org/")[-1].strip()


def get_license_by_url(url):
    cleaned_url = url.split("creativecommons.org")[-1]
    mapping = {
        "/licenses/by/4.0/": "cc-by",
        "/licenses/by-sa/4.0/": "cc-by-sa",
        "/licenses/by-nd/4.0/": "cc-by-nd",
        "/licenses/by-nc/4.0/": "cc-by-nc",
        "/licenses/by-nc-sa/4.0/": "cc-by-nc-sa",
        "/licenses/by-nc-nd/4.0/": "cc-by-nc-nd",
        "/publicdomain/zero/1.0/": "cc0",
    }
    return mapping[cleaned_url]
