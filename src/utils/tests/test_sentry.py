from unittest import TestCase
from unittest.mock import MagicMock, patch


class TestLogError(TestCase):

    @patch("utils.sentry.capture_exception")
    @patch("utils.sentry.get_isolation_scope")
    @patch("researchhub.settings.PRODUCTION", True)
    def test_base_error_records_str_of_base_error_not_message(
        self, mock_scope_fn, mock_capture
    ):
        scope = MagicMock()
        mock_scope_fn.return_value = scope

        from utils.sentry import log_error

        base = ValueError("original")
        raised = RuntimeError("wrapper")
        log_error(raised, base_error=base, message="context msg")

        scope.set_extra.assert_any_call("base_error", str(base))
        scope.set_extra.assert_any_call("message", "context msg")
        mock_capture.assert_called_once_with(raised)

    @patch("utils.sentry.capture_exception")
    @patch("utils.sentry.get_isolation_scope")
    @patch("researchhub.settings.PRODUCTION", True)
    def test_json_data_flattened_into_scope(self, mock_scope_fn, mock_capture):
        scope = MagicMock()
        mock_scope_fn.return_value = scope

        from utils.sentry import log_error

        exc = RuntimeError("err")
        log_error(exc, json_data={"outer": {"inner_key": "val"}})
        scope.set_extra.assert_any_call("outer_inner_key", "val")


class TestLogRequestError(TestCase):

    @patch("utils.sentry.capture_exception")
    @patch("utils.sentry.get_isolation_scope")
    @patch("researchhub.settings.PRODUCTION", True)
    def test_string_message_wrapped_in_exception(self, mock_scope_fn, mock_capture):
        scope = MagicMock()
        mock_scope_fn.return_value = scope

        from utils.sentry import log_request_error

        response = MagicMock()
        response.reason = "Not Found"
        log_request_error(response, "some error message")

        captured = mock_capture.call_args[0][0]
        self.assertIsInstance(captured, Exception)
        self.assertEqual(str(captured), "some error message")

    @patch("utils.sentry.capture_exception")
    @patch("utils.sentry.get_isolation_scope")
    @patch("researchhub.settings.PRODUCTION", True)
    def test_exception_message_passed_through(self, mock_scope_fn, mock_capture):
        scope = MagicMock()
        mock_scope_fn.return_value = scope

        from utils.sentry import log_request_error

        response = MagicMock()
        response.reason = "Server Error"
        exc = ValueError("real exception")
        log_request_error(response, exc)

        mock_capture.assert_called_once_with(exc)
