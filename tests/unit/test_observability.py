"""Unit tests for the Q19 correlation-id + structured-logging layer
(backend/shared/observability.py).

Covers:
  * request-id bind / current / reset round-trip via the contextvar.
  * sanitisation: trimming, length cap, control-char / newline stripping,
    empty → fresh-id fallback.
  * request_id_headers merges onto existing headers and always sets one.
  * JsonLogFormatter renders a single-line JSON record carrying the bound id +
    structured `extra=` fields, and never emits a raw newline mid-record.
  * RequestIdLogFilter stamps the record with the current id.
"""

from __future__ import annotations

import json
import logging

from backend.shared import observability as obs


def setup_function(_fn):
    # Each test starts from a clean context so a leaked id can't cross tests.
    obs.reset_request_id()


def teardown_function(_fn):
    obs.reset_request_id()


# ---------------------------------------------------------------------------
# Bind / current / reset.
# ---------------------------------------------------------------------------
def test_bind_returns_and_sets_current():
    rid = obs.bind_request_id("abc-123")
    assert rid == "abc-123"
    assert obs.current_request_id() == "abc-123"


def test_bind_generates_when_absent():
    rid = obs.bind_request_id(None)
    assert rid  # non-empty
    assert obs.current_request_id() == rid
    # uuid4 hex is 32 chars.
    assert len(rid) == 32


def test_reset_clears():
    obs.bind_request_id("x")
    obs.reset_request_id()
    assert obs.current_request_id() is None


def test_current_is_none_outside_request():
    assert obs.current_request_id() is None


# ---------------------------------------------------------------------------
# Sanitisation.
# ---------------------------------------------------------------------------
def test_sanitise_trims_and_caps():
    long = "a" * 500
    rid = obs.bind_request_id("   " + long + "   ")
    assert len(rid) == obs._MAX_REQUEST_ID_LEN
    assert set(rid) == {"a"}


def test_sanitise_strips_control_and_newline_chars():
    # A forged id trying to inject a newline (log forging) must be neutralised.
    rid = obs.bind_request_id("good\nEVIL log line")
    assert "\n" not in rid
    # spaces are dropped too (not in the allow-set) → "goodEVILlogline"
    assert rid == "goodEVILlogline"


def test_sanitise_empty_falls_back_to_fresh():
    rid = obs.bind_request_id("   ")  # whitespace only
    assert len(rid) == 32  # fresh uuid hex


def test_sanitise_all_invalid_falls_back_to_fresh():
    rid = obs.bind_request_id("\n\t  ")
    assert len(rid) == 32


def test_sanitise_preserves_traceparent_shape():
    tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    rid = obs.bind_request_id(tp)
    assert rid == tp


# ---------------------------------------------------------------------------
# request_id_headers.
# ---------------------------------------------------------------------------
def test_request_id_headers_uses_current():
    obs.bind_request_id("trace-7")
    headers = obs.request_id_headers()
    assert headers[obs.REQUEST_ID_HEADER] == "trace-7"


def test_request_id_headers_merges_onto_extra():
    obs.bind_request_id("trace-9")
    headers = obs.request_id_headers({"X-Internal-Token": "secret"})
    assert headers["X-Internal-Token"] == "secret"
    assert headers[obs.REQUEST_ID_HEADER] == "trace-9"


def test_request_id_headers_mints_when_unbound():
    # No id bound → still produces a trace id rather than omitting it.
    headers = obs.request_id_headers()
    assert headers[obs.REQUEST_ID_HEADER]
    assert len(headers[obs.REQUEST_ID_HEADER]) == 32


# ---------------------------------------------------------------------------
# JSON formatter + filter.
# ---------------------------------------------------------------------------
def _make_record(msg: str, **extra) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="patentmind.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_filter_stamps_request_id():
    obs.bind_request_id("rid-42")
    rec = _make_record("hello")
    obs.RequestIdLogFilter().filter(rec)
    assert rec.request_id == "rid-42"


def test_filter_stamps_dash_when_unbound():
    rec = _make_record("hello")
    obs.RequestIdLogFilter().filter(rec)
    assert rec.request_id == "-"


def test_json_formatter_single_line_and_fields():
    obs.bind_request_id("rid-77")
    rec = _make_record("an event", endpoint="/v1/oa/analyze", tenant="tenant_a")
    obs.RequestIdLogFilter().filter(rec)
    out = obs.JsonLogFormatter("gateway").format(rec)
    # Single line.
    assert "\n" not in out
    parsed = json.loads(out)
    assert parsed["message"] == "an event"
    assert parsed["service"] == "gateway"
    assert parsed["request_id"] == "rid-77"
    assert parsed["level"] == "INFO"
    # structured extras folded in as top-level keys.
    assert parsed["endpoint"] == "/v1/oa/analyze"
    assert parsed["tenant"] == "tenant_a"


def test_json_formatter_handles_unserialisable_extra():
    rec = _make_record("x", weird=object())
    obs.RequestIdLogFilter().filter(rec)
    out = obs.JsonLogFormatter("ai_engine").format(rec)
    parsed = json.loads(out)  # must not raise
    assert "weird" in parsed  # rendered via repr fallback


def test_json_formatter_renders_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord(
            "patentmind.test",
            logging.ERROR,
            __file__,
            1,
            "failed",
            (),
            sys.exc_info(),
        )
    obs.RequestIdLogFilter().filter(rec)
    parsed = json.loads(obs.JsonLogFormatter("gateway").format(rec))
    assert "exc" in parsed
    assert "ValueError" in parsed["exc"]
