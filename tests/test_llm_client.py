"""llm/client.py against a fake LM Studio (httpx.MockTransport): chat, streamed chat, embeddings, JSON extraction,
the one-at-a-time gate and the circuit breaker. Never needs LM Studio."""
import json
import sys
import threading
import time
from pathlib import Path

import httpx
import numpy as np
import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm import client  # noqa: E402


def fake(monkeypatch, handler):
    """Route every client request to handler(request) -> httpx.Response; returns the list of requests seen."""
    seen = []

    def wrap(request):
        seen.append(request)
        return handler(request)
    monkeypatch.setattr(client, "_transport", httpx.MockTransport(wrap))
    return seen


def sse(*events: str) -> bytes:
    return "".join(f"data: {e}\n\n" for e in events).encode()


def delta(text: str | None) -> str:
    d = {} if text is None else {"content": text}
    return json.dumps({"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": d}]})


# ------------------------------------------------------------------ chat

def test_chat_sends_the_messages_and_limits(monkeypatch):
    seen = fake(monkeypatch, lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "Hi."}}]}))
    msgs = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hello"}]
    assert client.chat(msgs, max_tokens=50, temperature=0.0) == "Hi."
    body = json.loads(seen[0].content)
    assert seen[0].url.path.endswith("/chat/completions")
    assert body["messages"] == msgs and body["max_tokens"] == 50 and body["temperature"] == 0.0
    assert body["model"] == client.LLM_CHAT_MODEL and "stream" not in body


def test_chat_errors_are_connection_errors(monkeypatch):
    fake(monkeypatch, lambda r: httpx.Response(500, json={"error": "model not loaded"}))
    with pytest.raises(client.LLMConnectionError, match="500"):
        client.chat([{"role": "user", "content": "x"}])

    def refuse(r):
        raise httpx.ConnectError("refused", request=r)
    fake(monkeypatch, refuse)
    with pytest.raises(client.LLMConnectionError):
        client.chat([{"role": "user", "content": "x"}])
    fake(monkeypatch, lambda r: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(client.LLMConnectionError, match="not a chat completion"):
        client.chat([{"role": "user", "content": "x"}])


def test_chat_waits_for_the_whole_reply_and_says_what_is_down(monkeypatch):
    ok = {"choices": [{"message": {"content": "Hi."}}]}
    seen = fake(monkeypatch, lambda r: httpx.Response(200, json=ok))
    client.chat([{"role": "user", "content": "x"}], max_tokens=400)
    client.chat([{"role": "user", "content": "x"}], max_tokens=50)
    client.complete("sys", "user")
    reads = [r.extensions["timeout"]["read"] for r in seen]
    # 400 tokens at the measured 4.3 tokens/s is 93 s of generation after the prompt: more than the old 120 s cut
    assert reads[0] >= 30 + 400 / 2 and reads[1] == reads[2] == client.TIMEOUT
    assert {r.extensions["timeout"]["connect"] for r in seen} == {client.CONNECT_TIMEOUT}

    def raising(exc):
        def handler(r):
            raise exc("boom", request=r)
        return handler
    for exc, timeout, down in [(httpx.ReadTimeout, True, False), (httpx.ConnectError, False, True),
                               (httpx.ConnectTimeout, False, True), (httpx.RemoteProtocolError, False, False)]:
        fake(monkeypatch, raising(exc))
        for call in (lambda: client.chat([{"role": "user", "content": "x"}]),
                     lambda: next(client.chat_stream([{"role": "user", "content": "x"}])),
                     lambda: client.embed(["x"])):
            with pytest.raises(client.LLMConnectionError) as err:
                call()
            assert isinstance(err.value, client.LLMTimeoutError) == timeout and err.value.down == down, exc
    fake(monkeypatch, lambda r: httpx.Response(500, json={"error": "model not loaded"}))
    with pytest.raises(client.LLMConnectionError) as err:
        client.chat([{"role": "user", "content": "x"}])
    assert not err.value.down  # up, but failing: not a reason to switch the model off for everyone


def test_complete_and_call_llm_still_work(monkeypatch):
    replies = iter(["Plain text.", "Sure:\n```json\n{\"n\": 3, \"why\": \"x\"}\n```"])
    seen = fake(monkeypatch, lambda r: httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]}))
    assert client.complete("sys", "user") == "Plain text."
    assert json.loads(seen[0].content)["model"] == client.LLM_MODEL

    class Out(BaseModel):
        n: int
        why: str
    assert client.call_llm("sys", "user", Out) == Out(n=3, why="x")


# ------------------------------------------------------------------ streaming

def test_chat_stream_yields_deltas_until_done(monkeypatch):
    # the body arrives in pieces that split lines and events; a comment, an empty delta and a role-only delta
    raw = b": keep-alive\n\n" + sse(delta(None), delta("Land "), delta("is "), delta(""), delta("pending."),
                                    "[DONE]", delta("after done"))
    pieces = [raw[i:i + 7] for i in range(0, len(raw), 7)]
    seen = fake(monkeypatch, lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                                      content=iter(pieces)))
    out = list(client.chat_stream([{"role": "user", "content": "x"}], max_tokens=20))
    assert out == ["Land ", "is ", "pending."]
    body = json.loads(seen[0].content)
    assert body["stream"] is True and body["max_tokens"] == 20


def test_chat_stream_is_lazy_and_needs_an_end(monkeypatch):
    stop = json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    seen = fake(monkeypatch, lambda r: httpx.Response(200, content=sse(delta("a"), delta("b"), stop)))
    gen = client.chat_stream([{"role": "user", "content": "x"}])
    assert seen == []  # nothing is sent before the first next()
    assert "".join(gen) == "ab"  # a finish_reason ends it without [DONE]
    # a stream that just stops (no [DONE], no finish_reason) is a cut-off answer, not a whole one
    fake(monkeypatch, lambda r: httpx.Response(200, content=sse(delta("a"), delta("b"))))
    gen = client.chat_stream([{"role": "user", "content": "x"}])
    assert next(gen) == "a" and next(gen) == "b"
    with pytest.raises(client.LLMConnectionError, match="before \\[DONE\\]"):
        next(gen)


def test_chat_stream_keeps_unicode_line_separators(monkeypatch):
    # JSON may carry U+2028, U+2029 and U+0085 raw inside a string; only CR and LF end an event line. The body
    # arrives in 3-byte pieces, so the multi-byte characters are split between pieces too.
    text = "Land acquisition is \u0085pending ₹"
    event = json.dumps({"choices": [{"index": 0, "delta": {"content": text}}]}, ensure_ascii=False)
    raw = f"data: {event}\r\n\r\ndata: [DONE]\r\n\r\n".encode()
    fake(monkeypatch, lambda r: httpx.Response(200, content=iter([raw[i:i + 3] for i in range(0, len(raw), 3)])))
    assert list(client.chat_stream([{"role": "user", "content": "x"}])) == [text]


def test_chat_stream_errors(monkeypatch):
    fake(monkeypatch, lambda r: httpx.Response(400, json={"error": "context length exceeded"}))
    with pytest.raises(client.LLMConnectionError, match="context length"):
        list(client.chat_stream([{"role": "user", "content": "x"}]))

    def refuse(r):
        raise httpx.ConnectError("refused", request=r)
    fake(monkeypatch, refuse)
    with pytest.raises(client.LLMConnectionError):
        next(client.chat_stream([{"role": "user", "content": "x"}]))

    fake(monkeypatch, lambda r: httpx.Response(200, content=sse(delta("a"), json.dumps({"error": "crashed"}))))
    gen = client.chat_stream([{"role": "user", "content": "x"}])
    assert next(gen) == "a"
    with pytest.raises(client.LLMConnectionError, match="crashed"):
        next(gen)

    for bad in ('{"choices": ["x"]}', '{"choices": [{"delta": "x"}]}', '{"choices": {"delta": {}}}'):
        fake(monkeypatch, lambda r, bad=bad: httpx.Response(200, content=sse(delta("a"), bad, "[DONE]")))
        gen = client.chat_stream([{"role": "user", "content": "x"}])
        assert next(gen) == "a"
        with pytest.raises(client.LLMConnectionError, match="not a chat completion chunk"):
            next(gen)


class Events(httpx.SyncByteStream):
    """A server-sent-event body that counts what it sent and knows when the client closed it."""

    def __init__(self, events):
        self.events, self.sent, self.closed = events, 0, False

    def __iter__(self):
        for e in self.events:
            self.sent += 1
            yield e

    def close(self):
        self.closed = True


def test_chat_stream_close_early_closes_the_connection(monkeypatch):
    body = Events([sse(delta(str(i))) for i in range(50)] + [sse("[DONE]")])
    fake(monkeypatch, lambda r: httpx.Response(200, stream=body))
    gen = client.chat_stream([{"role": "user", "content": "x"}])
    assert [next(gen), next(gen)] == ["0", "1"]
    assert not body.closed
    gen.close()  # the viewer pressed stop: the response is closed, so LM Studio stops generating
    assert body.closed and body.sent < 10


# ------------------------------------------------------------------ embeddings

def test_embed_batches_orders_and_normalises(monkeypatch):
    def handler(r):
        body = json.loads(r.content)
        data = [{"index": i, "embedding": [float(len(t)), 1.0, 0.0]} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"data": list(reversed(data)), "model": body["model"]})
    seen = fake(monkeypatch, handler)
    texts = ["a", "bb", "ccc", "", "eeeee"]
    m = client.embed(texts, batch=2)
    assert len(seen) == 3 and m.dtype == np.float32 and m.shape == (5, 3)
    assert np.allclose(np.linalg.norm(m, axis=1), 1.0)
    want = np.array([[len(t) or 1, 1, 0] for t in texts], float)  # the empty text went as " "
    assert np.allclose(m, want / np.linalg.norm(want, axis=1, keepdims=True), atol=1e-6)
    assert json.loads(seen[0].content)["model"] == client.LLM_EMBED_MODEL
    assert json.loads(seen[1].content)["input"] == ["ccc", " "]
    assert client.embed([]).shape == (0, 0)


def test_embed_errors(monkeypatch):
    fake(monkeypatch, lambda r: httpx.Response(404, json={"error": "no embedding model"}))
    with pytest.raises(client.LLMConnectionError, match="404"):
        client.embed(["x"])
    fake(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]}))
    with pytest.raises(client.LLMConnectionError, match="for 2 texts"):
        client.embed(["x", "y"])


# ------------------------------------------------------------------ JSON

@pytest.mark.parametrize("text, want", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"calls": [{"tool": "get_project", "args": {"key": "PRJ-000001"}}]}\n```',
     {"calls": [{"tool": "get_project", "args": {"key": "PRJ-000001"}}]}),
    ('Here you go [as asked]:\n```\n[{"i": 0, "relevant": true}]\n```\nDone.', [{"i": 0, "relevant": True}]),
    ('The plan {not json} is: {"q": "brace } and [ inside a string", "n": [1, 2]} ok',
     {"q": "brace } and [ inside a string", "n": [1, 2]}),
    ('{"a": [1, 2,], "b": {"c": 3,},}', {"a": [1, 2], "b": {"c": 3}}),
    ('first {"x": 1} then {"y": 2}', {"x": 1}),
    ('escaped \\" quote: {"s": "say \\"hi\\" {"}', {"s": 'say "hi" {'}),
])
def test_extract_json(text, want):
    assert client.extract_json(text) == want


@pytest.mark.parametrize("text, want", [
    # a citation or a year in the prose is not the answer when an object follows
    ('Based on [1] and [2], the plan: {"calls": [{"tool": "x"}]}', {"calls": [{"tool": "x"}]}),
    ('Note (see [2024]): {"k": 1}', {"k": 1}),
    # a list of plain values is still the answer when nothing else is there, or when it is fenced
    ("[0, 2]", [0, 2]),
    ("Relevant: [1, 3]", [1, 3]),
    ('```json\n[0, 2]\n```\nand {"a": 1}', [0, 2]),
])
def test_extract_json_skips_prose_brackets(text, want):
    assert client.extract_json(text) == want


def test_extract_json_wanted_type():
    assert client.extract_json('[{"a": 1}] then {"b": 2}', dict) == {"b": 2}
    assert client.extract_json('{"a": [1]} then [2]', list) == [2]
    assert client.extract_json("Based on [1]: [2, 3]", list) == [1]  # a plain list asked for: prose looks the same
    with pytest.raises(ValueError):
        client.extract_json("[1, 2]", dict)
    with pytest.raises(TypeError):
        client.extract_json("{}", str)


@pytest.mark.parametrize("text", [
    "", "no json here", '{"cut": "off by max_tokens', "[unbalanced",
    # cut off by max_tokens: never one of its complete inner parts, and never a citation before it
    '{"calls": [{"tool": "search_projects", "args": {"q": "x"}}, {"tool": "get_pro',
    'See [1]. {"calls": [{"tool": "x"}, {"too',
])
def test_extract_json_raises_value_error(text):
    with pytest.raises(ValueError):
        client.extract_json(text)
    with pytest.raises(ValueError):
        client.extract_json(text, dict)


def test_call_llm_retries_a_truncated_reply(monkeypatch):
    replies = iter(['{"n": 3, "why": "cut off', 'Answer [1]: {"n": 4, "why": "x"}'])
    fake(monkeypatch, lambda r: httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]}))

    class Out(BaseModel):
        n: int
        why: str
    assert client.call_llm("sys", "user", Out) == Out(n=4, why="x")


# ------------------------------------------------------------------ gate and breaker

def test_gate_times_out_and_releases():
    with client.gate(1) as ok:
        assert ok
        t0 = time.monotonic()
        with client.gate(0.05) as again:  # not re-entrant: a second take waits and gives up
            assert not again
        assert time.monotonic() - t0 >= 0.04
    with client.gate(0) as ok:  # released on exit, and the timed-out take released nothing
        assert ok
    with pytest.raises(RuntimeError), client.gate(0) as ok:
        raise RuntimeError("boom")
    with client.gate(0) as ok:  # released after an error in the block too
        assert ok


def test_chat_active_while_holding_or_waiting():
    assert not client.chat_active()
    held, release, waiting_done = threading.Event(), threading.Event(), threading.Event()

    def background():
        with client.gate(5) as ok:
            assert ok
            held.set()
            release.wait(5)

    def chat_request():
        with client.gate(5, chat=True) as ok:
            assert ok
        waiting_done.set()
    bg = threading.Thread(target=background)
    bg.start()
    held.wait(5)
    assert not client.chat_active()
    ch = threading.Thread(target=chat_request)
    ch.start()
    deadline = time.monotonic() + 5
    while not client.chat_active() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert client.chat_active()                    # waiting for the gate counts
    assert not client.wait_chat_idle(max_s=0.05, poll_s=0.01)
    release.set()
    bg.join(5)
    ch.join(5)
    assert waiting_done.is_set() and not client.chat_active()
    assert client.wait_chat_idle(max_s=0)
    with client.gate(1, chat=True):
        assert client.chat_active()
    assert not client.chat_active()


def test_a_waiting_chat_goes_before_the_next_background_take():
    order, held, release = [], threading.Event(), threading.Event()

    def background():
        with client.gate(5) as ok:
            order.append("bg1" if ok else "bg1 busy")
            held.set()
            release.wait(5)
        with client.gate(5) as ok:  # straight back for its next item: a semaphore would let it barge in
            order.append("bg2" if ok else "bg2 busy")

    def chat_request():
        with client.gate(5, chat=True) as ok:
            order.append("chat" if ok else "chat busy")
            time.sleep(0.05)
    bg = threading.Thread(target=background)
    bg.start()
    held.wait(5)
    ch = threading.Thread(target=chat_request)
    ch.start()
    deadline = time.monotonic() + 5
    while not client.chat_active() and time.monotonic() < deadline:
        time.sleep(0.005)
    release.set()
    bg.join(10)
    ch.join(10)
    assert order == ["bg1", "chat", "bg2"]

    with client.gate(1, chat=True):          # a background take gives up within its own wait_s
        t0 = time.monotonic()
        with client.gate(0.1) as ok:
            assert not ok
        assert 0.09 <= time.monotonic() - t0 < 1
    t0 = time.monotonic()
    with client.gate(0) as ok:               # and does not wait at all when no chat is active
        assert ok and time.monotonic() - t0 < 0.05


def test_circuit_breaker(monkeypatch):
    monkeypatch.setattr(client, "_down_at", -1e9)
    assert not client.down_recently()
    client.mark_down()
    assert client.down_recently() and client.down_recently(5)
    assert not client.down_recently(0)
