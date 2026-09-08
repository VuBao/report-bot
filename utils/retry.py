"""Small retry helpers for temporary failures from external services."""

import logging
import time


TRANSIENT_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
_TRANSIENT_EXCEPTION_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "ConnectionError",
    "ConnectionResetError",
    "ReadTimeout",
    "ServiceUnavailable",
    "Timeout",
    "TimeoutError",
    "TransportError",
}
_TRANSIENT_MESSAGE_PARTS = (
    "timed out",
    "timeout",
    "temporarily unavailable",
    "service is currently unavailable",
    "connection reset",
    "connection aborted",
    "connection refused",
)


def _exception_chain(exc):
    """Yield an exception and its explicit/implicit causes without looping."""
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _status_from_value(value):
    if isinstance(value, dict):
        for key in ("code", "status_code", "status"):
            candidate = value.get(key)
            if isinstance(candidate, int) or (isinstance(candidate, str) and candidate.isdigit()):
                return int(candidate)
        for key in ("error", "response"):
            status = _status_from_value(value.get(key))
            if status is not None:
                return status
    return None


def exception_http_status(exc):
    """Best-effort HTTP status extraction across gspread/Google/AI clients."""
    for error in _exception_chain(exc):
        response = getattr(error, "response", None)
        for candidate in (
            getattr(response, "status_code", None),
            getattr(response, "status", None),
            getattr(error, "status_code", None),
        ):
            if isinstance(candidate, int) or (isinstance(candidate, str) and candidate.isdigit()):
                return int(candidate)
        if response is not None:
            try:
                status = _status_from_value(response.json())
            except (AttributeError, TypeError, ValueError):
                status = None
            if status is not None:
                return status
        for arg in getattr(error, "args", ()):
            status = _status_from_value(arg)
            if status is not None:
                return status
    return None


def is_transient_external_error(exc):
    """Return whether retrying a failed network/service operation is reasonable."""
    status = exception_http_status(exc)
    if status in TRANSIENT_HTTP_STATUSES or (status is not None and 500 <= status < 600):
        return True
    for error in _exception_chain(exc):
        if error.__class__.__name__ in _TRANSIENT_EXCEPTION_NAMES:
            return True
        message = str(error).lower()
        if any(part in message for part in _TRANSIENT_MESSAGE_PARTS):
            return True
    return False


def call_with_retry(
    function,
    *args,
    attempts=3,
    delays=(1, 2),
    operation="external service call",
    logger=None,
    retry_if=is_transient_external_error,
    **kwargs,
):
    """Call a synchronous function and retry only temporary failures."""
    log = logger or logging.getLogger(__name__)
    for attempt in range(1, attempts + 1):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            if not retry_if(exc) or attempt == attempts:
                raise
            delay = delays[min(attempt - 1, len(delays) - 1)] if delays else 0
            log.warning(
                "[%s] Temporary failure (%s, HTTP %s); retry %s/%s in %ss",
                operation,
                exc.__class__.__name__,
                exception_http_status(exc) or "unknown",
                attempt + 1,
                attempts,
                delay,
            )
            if delay:
                time.sleep(delay)
