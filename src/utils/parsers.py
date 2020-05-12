from django.utils import timezone
from rest_framework.parsers import BaseParser


ISO_DATE_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'


class PlainTextParser(BaseParser):
    """
    Plain text parser.
    """
    media_type = 'text/plain'

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
        if attribute[:2] != '__':
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
