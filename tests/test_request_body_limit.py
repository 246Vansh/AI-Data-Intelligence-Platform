"""
Step 79 - request-body limit enforced at the ASGI receive layer.

MaxBodySizeMiddleware (backend/main.py) must stop an oversized body
while it is being received - including a chunked request with no
Content-Length - instead of letting FastAPI/Starlette spool the whole
multipart body to disk before the upload route can reject it.

Starlette's TestClient reads the entire request body before calling
the app (one http.request message), so it cannot show that a producer
stops being read early. The streaming tests below therefore drive the
ASGI app directly with a counting receive() and no sleeps.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import MaxBodySizeMiddleware, app


REJECTION_BODY = b'{"detail":"Request body exceeds the maximum allowed size."}'

ORIGIN = "http://localhost:5173"


# =========================================================
# RAW ASGI HELPERS
# =========================================================


def _http_scope(path: str, headers: list[tuple[bytes, bytes]], method: str = "POST"):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


class _ChunkProducer:
    """
    receive() that streams `chunks` as http.request messages and
    records how many it handed out - the proof of whether the body
    was consumed to completion.
    """

    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks
        self.consumed = 0

    async def __call__(self):
        if self.consumed < len(self._chunks):
            body = self._chunks[self.consumed]
            self.consumed += 1
            return {
                "type": "http.request",
                "body": body,
                "more_body": self.consumed < len(self._chunks),
            }

        return {"type": "http.disconnect"}

    @property
    def exhausted(self) -> bool:
        return self.consumed == len(self._chunks)


def _run(asgi_app, scope, receive) -> list[dict]:
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    asyncio.run(asgi_app(scope, receive, send))
    return sent


def _status(sent: list[dict]) -> int:
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert len(starts) == 1, sent
    return starts[0]["status"]


def _body(sent: list[dict]) -> bytes:
    return b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )


def _multipart_upload_chunks(
    boundary: bytes, chunk_count: int, chunk_size: int
) -> list[bytes]:
    head = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="big.csv"\r\n'
        b"Content-Type: text/csv\r\n\r\n"
        b"a,b\n"
    )
    row_chunk = (b"1,2\n" * (chunk_size // 4))[:chunk_size]
    tail = b"\r\n--" + boundary + b"--\r\n"
    return [head] + [row_chunk] * chunk_count + [tail]


async def _echo_body_app(scope, receive, send):
    """Inner app that reads the full body and reports its size."""

    total = 0
    while True:
        message = await receive()
        total += len(message.get("body", b""))
        if not message.get("more_body", False):
            break

    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": str(total).encode()})


# =========================================================
# CONTENT-LENGTH: EARLY REJECTION (UNCHANGED BEHAVIOR)
# =========================================================


def test_oversized_content_length_is_rejected_with_existing_413_body(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 10)

    response = TestClient(app).post(
        "/api/analyze",
        content=b"x" * 100,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.content == REJECTION_BODY


def test_oversized_content_length_is_rejected_without_reading_body(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 10)
    producer = _ChunkProducer([b"x" * 5] * 10)
    scope = _http_scope("/api/analyze", [(b"content-length", b"50")])

    sent = _run(MaxBodySizeMiddleware(_echo_body_app), scope, producer)

    assert _status(sent) == 413
    assert _body(sent) == REJECTION_BODY
    assert producer.consumed == 0


# =========================================================
# NO CONTENT-LENGTH: REJECTION DURING RECEIPT
# =========================================================


def test_chunked_upload_without_content_length_stops_at_receive_layer(monkeypatch):
    """
    Full app stack, real upload route: a multipart body with no
    Content-Length is cut off once the limit is crossed, the producer
    is never drained, and the client gets the middleware's 413 - not
    FastAPI's 400 for an unreadable body, and not the route's own 413.
    """

    limit = 8 * 1024
    chunk_size = 1024
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", limit)

    boundary = b"step79boundary"
    producer = _ChunkProducer(
        _multipart_upload_chunks(boundary, chunk_count=1000, chunk_size=chunk_size)
    )
    scope = _http_scope(
        "/api/dataset/upload",
        [(b"content-type", b"multipart/form-data; boundary=" + boundary)],
    )

    sent = _run(app, scope, producer)

    assert _status(sent) == 413
    assert _body(sent) == REJECTION_BODY
    assert not producer.exhausted
    # Head chunk + just enough row chunks to cross the limit.
    assert producer.consumed <= limit // chunk_size + 2


def test_chunked_body_over_limit_is_not_consumed_to_completion(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 100)
    producer = _ChunkProducer([b"x" * 30] * 50)
    scope = _http_scope("/anything", [])

    sent = _run(MaxBodySizeMiddleware(_echo_body_app), scope, producer)

    assert _status(sent) == 413
    assert _body(sent) == REJECTION_BODY
    # 4 x 30 = 120 > 100: the 4th chunk crosses the limit.
    assert producer.consumed == 4


def test_body_exactly_at_limit_passes(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 100)
    producer = _ChunkProducer([b"x" * 25] * 4)

    sent = _run(MaxBodySizeMiddleware(_echo_body_app), _http_scope("/x", []), producer)

    assert _status(sent) == 200
    assert _body(sent) == b"100"
    assert producer.exhausted


# =========================================================
# WITHIN LIMIT: PASSES THROUGH
# =========================================================


def test_chunked_body_within_limit_passes_through(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 1000)
    producer = _ChunkProducer([b"x" * 10] * 5)

    sent = _run(MaxBodySizeMiddleware(_echo_body_app), _http_scope("/x", []), producer)

    assert _status(sent) == 200
    assert _body(sent) == b"50"
    assert producer.exhausted


def test_request_within_limit_reaches_route():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_invalid_content_length_falls_back_to_counting(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 100)
    producer = _ChunkProducer([b"x" * 10] * 3)
    scope = _http_scope("/x", [(b"content-length", b"not-a-number")])

    sent = _run(MaxBodySizeMiddleware(_echo_body_app), scope, producer)

    assert _status(sent) == 200
    assert _body(sent) == b"30"


# =========================================================
# NON-HTTP SCOPES
# =========================================================


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
def test_non_http_scopes_pass_through_untouched(monkeypatch, scope_type):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 0)
    seen = {}

    async def inner(scope, receive, send):
        seen["receive"] = receive
        seen["send"] = send

    async def receive():
        return {"type": f"{scope_type}.startup"}

    async def send(message):
        pass

    asyncio.run(MaxBodySizeMiddleware(inner)({"type": scope_type}, receive, send))

    assert seen["receive"] is receive
    assert seen["send"] is send


# =========================================================
# ALREADY-STARTED RESPONSE
# =========================================================


def test_limit_crossed_after_response_started_sends_no_second_response(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 10)
    producer = _ChunkProducer([b"x" * 6] * 5)

    async def responds_then_reads(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    with pytest.raises(Exception):
        asyncio.run(
            MaxBodySizeMiddleware(responds_then_reads)(
                _http_scope("/x", []), producer, send
            )
        )

    assert _status(sent) == 200
    assert REJECTION_BODY not in _body(sent)
    assert not producer.exhausted


# =========================================================
# MIDDLEWARE ORDERING / CORS
# =========================================================


def test_cors_still_wraps_the_body_limit_middleware():
    classes = [m.cls for m in app.user_middleware]

    assert MaxBodySizeMiddleware in classes
    cors_index = next(
        i for i, cls in enumerate(classes) if cls.__name__ == "CORSMiddleware"
    )
    assert cors_index < classes.index(MaxBodySizeMiddleware)


def test_413_carries_cors_headers_for_allowed_origin(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 10)

    response = TestClient(app).post(
        "/api/analyze",
        content=b"x" * 100,
        headers={"content-type": "application/json", "origin": ORIGIN},
    )

    assert response.status_code == 413
    assert response.content == REJECTION_BODY
    assert response.headers["access-control-allow-origin"] == ORIGIN


# =========================================================
# EXCEPTION HANDLING: ONLY THE MIDDLEWARE'S OWN SIGNAL
# =========================================================


def _wrap_inner_app(record: dict):
    """
    Build the real middleware stack and wrap whatever sits directly
    inside MaxBodySizeMiddleware, recording how that inner app ends.
    """

    stack = app.build_middleware_stack()
    node = stack
    while not isinstance(node, MaxBodySizeMiddleware):
        node = node.app
    real_inner = node.app

    async def recording_inner(scope, receive, send):
        async def recording_send(message):
            if message["type"] == "http.response.start":
                record["inner_status"] = message["status"]
            await send(message)

        try:
            await real_inner(scope, receive, recording_send)
        except BaseException as exc:
            record["inner_raised"] = exc
            raise
        record["inner_raised"] = None

    node.app = recording_inner
    return stack


@pytest.mark.parametrize(
    "path,content_type,chunks",
    [
        (
            "/api/dataset/upload",
            b"multipart/form-data; boundary=bb",
            _multipart_upload_chunks(b"bb", chunk_count=1000, chunk_size=1024),
        ),
        ("/api/analyze", b"application/json", [b"x" * 1024] * 50),
    ],
)
def test_fastapi_path_converts_signal_to_400_that_middleware_replaces(
    monkeypatch, path, content_type, chunks
):
    """
    Verified FastAPI behavior: the receive error never reaches the
    middleware as an exception - FastAPI wraps it in HTTPException(400),
    Starlette's ExceptionMiddleware sends that 400, and the inner app
    returns normally. The middleware drops the 400 and sends the 413.
    """

    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 8 * 1024)
    record: dict = {}
    stack = _wrap_inner_app(record)
    producer = _ChunkProducer(chunks)

    sent = _run(stack, _http_scope(path, [(b"content-type", content_type)]), producer)

    assert record["inner_raised"] is None
    assert record["inner_status"] == 400
    assert _status(sent) == 413
    assert _body(sent) == REJECTION_BODY
    assert not producer.exhausted


def test_raw_signal_propagating_from_inner_app_becomes_413(monkeypatch):
    """Plain ASGI inner app that lets the limit signal propagate."""

    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 10)
    producer = _ChunkProducer([b"x" * 6] * 5)
    raised: dict = {}

    async def reads_without_catching(scope, receive, send):
        try:
            while (await receive()).get("more_body", False):
                pass
        except BaseException as exc:
            raised["exc"] = exc
            raise

    sent = _run(MaxBodySizeMiddleware(reads_without_catching), _http_scope("/x", []), producer)

    assert type(raised["exc"]).__name__ == "_RequestBodyTooLarge"
    assert _status(sent) == 413
    assert _body(sent) == REJECTION_BODY


def test_unrelated_exception_after_limit_crossed_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 10)
    producer = _ChunkProducer([b"x" * 6] * 5)

    async def fails_for_another_reason(scope, receive, send):
        try:
            while (await receive()).get("more_body", False):
                pass
        except Exception:
            pass
        raise RuntimeError("unrelated application failure")

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    with pytest.raises(RuntimeError, match="unrelated application failure"):
        asyncio.run(
            MaxBodySizeMiddleware(fails_for_another_reason)(
                _http_scope("/x", []), producer, send
            )
        )

    # No 413 masking the real failure (the outer ServerErrorMiddleware
    # turns it into a 500 in the real stack).
    assert sent == []


def test_unrelated_exception_within_limit_propagates(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 1000)

    async def fails(scope, receive, send):
        await receive()
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        _run(MaxBodySizeMiddleware(fails), _http_scope("/x", []), _ChunkProducer([b"x"]))


def test_unrelated_exception_after_limit_in_real_stack_is_a_500(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 10)

    async def fails_for_another_reason(scope, receive, send):
        try:
            while (await receive()).get("more_body", False):
                pass
        except Exception:
            pass
        raise RuntimeError("unrelated application failure")

    stack = app.build_middleware_stack()
    node = stack
    while not isinstance(node, MaxBodySizeMiddleware):
        node = node.app
    node.app = fails_for_another_reason

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    with pytest.raises(RuntimeError):
        asyncio.run(stack(_http_scope("/x", []), _ChunkProducer([b"x" * 6] * 5), send))

    assert _status(sent) == 500
    assert REJECTION_BODY not in _body(sent)
