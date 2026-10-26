import json
import logging
from unittest import TestCase

from utils.log_formatters import UvicornAccessJsonFormatter


def _record(msg, args):
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


class UvicornAccessJsonFormatterTests(TestCase):
    def setUp(self):
        self.formatter = UvicornAccessJsonFormatter(
            "%(levelname)s %(name)s %(message)s"
        )

    def test_adds_http_attributes(self):
        # Arrange
        record = _record(
            '%s - "%s %s HTTP/%s" %d',
            ("203.0.113.7:0", "GET", "/api/paper/?page=2", "1.1", 200),
        )

        # Act
        output = json.loads(self.formatter.format(record))

        # Assert
        self.assertEqual(
            output["message"], '203.0.113.7:0 - "GET /api/paper/?page=2 HTTP/1.1" 200'
        )
        self.assertEqual(
            output["http"],
            {
                "method": "GET",
                "url": "/api/paper/?page=2",
                "version": "1.1",
                "status_code": 200,
            },
        )
        self.assertEqual(output["network"], {"client": {"ip": "203.0.113.7"}})

    def test_strips_port_from_ipv6_client(self):
        # Arrange
        record = _record(
            '%s - "%s %s HTTP/%s" %d', ("::1:51234", "POST", "/", "1.1", 201)
        )

        # Act
        output = json.loads(self.formatter.format(record))

        # Assert
        self.assertEqual(output["network"]["client"]["ip"], "::1")

    def test_unexpected_args_are_logged_without_http_attributes(self):
        # Arrange
        record = _record("something else: %s", ("value",))

        # Act
        output = json.loads(self.formatter.format(record))

        # Assert
        self.assertEqual(output["message"], "something else: value")
        self.assertNotIn("http", output)
        self.assertNotIn("network", output)
