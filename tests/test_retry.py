import unittest
from unittest.mock import AsyncMock, Mock, patch

from main import _run_async_prepare_call
from services.residence_card_service import (
    _is_transient_google_error,
    write_residence_card_form,
)
from utils.retry import call_with_retry, exception_http_status, is_transient_external_error


class FakeResponse:
    status_code = 503

    def json(self):
        return {
            "error": {
                "code": 503,
                "message": "The service is currently unavailable.",
                "status": "UNAVAILABLE",
            }
        }


class FakeGoogleError(Exception):
    def __init__(self):
        super().__init__({
            "code": 503,
            "message": "The service is currently unavailable.",
            "status": "UNAVAILABLE",
        })
        self.response = FakeResponse()


class RetryTests(unittest.TestCase):
    def test_google_503_is_transient(self):
        error = FakeGoogleError()
        self.assertEqual(exception_http_status(error), 503)
        self.assertTrue(is_transient_external_error(error))
        self.assertTrue(_is_transient_google_error(error))

    @patch("services.residence_card_service.time.sleep")
    @patch("services.residence_card_service._write_residence_card_form_once")
    def test_form_write_retries_google_503(self, write_once, sleep):
        write_once.side_effect = [FakeGoogleError(), {"tab_name": "EMPLOYEE", "created": False}]
        result = write_residence_card_form(
            "spreadsheet-id",
            "company",
            "branch",
            {"full_name": "EMPLOYEE"},
            "current",
            "future",
        )
        self.assertEqual(result["tab_name"], "EMPLOYEE")
        self.assertEqual(write_once.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_timeout_without_http_status_is_transient(self):
        self.assertTrue(is_transient_external_error(TimeoutError("Timed out")))
        self.assertTrue(is_transient_external_error(RuntimeError("Timed out")))

    def test_nested_timeout_is_transient(self):
        try:
            try:
                raise TimeoutError("socket timed out")
            except TimeoutError as cause:
                raise RuntimeError("provider failed") from cause
        except RuntimeError as error:
            self.assertTrue(is_transient_external_error(error))

    @patch("utils.retry.time.sleep")
    def test_call_retries_then_returns(self, sleep):
        operation = Mock(side_effect=[TimeoutError("Timed out"), "ok"])
        result = call_with_retry(operation, attempts=3, delays=(1, 2))
        self.assertEqual(result, "ok")
        self.assertEqual(operation.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch("utils.retry.time.sleep")
    def test_call_does_not_retry_validation_error(self, sleep):
        operation = Mock(side_effect=ValueError("invalid card"))
        with self.assertRaisesRegex(ValueError, "invalid card"):
            call_with_retry(operation, attempts=3, delays=(1, 2))
        self.assertEqual(operation.call_count, 1)
        sleep.assert_not_called()


class AsyncRetryTests(unittest.IsolatedAsyncioTestCase):
    @patch("main.asyncio.sleep")
    async def test_async_call_retries_telegram_timeout(self, sleep):
        operation = AsyncMock(side_effect=[TimeoutError("Timed out"), b"image"])
        result = await _run_async_prepare_call("download", operation)
        self.assertEqual(result, b"image")
        self.assertEqual(operation.call_count, 2)
        sleep.assert_awaited_once_with(1)


if __name__ == "__main__":
    unittest.main()
