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


def test_chat_stream_ends_without_done_and_is_lazy(monkeypatch):
    seen = fake(monkeypatch, lambda r: httpx.Response(200, content=sse(delta("a"), delta("b"))))
    gen = client.chat_stream([{"role": "user", "content": "x"}])
    assert seen == []  # nothing is sent before the first next()
    assert "".join(gen) == "ab"


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


def test_chat_stream_close_early_is_quiet(monkeypatch):
    fake(monkeypatch, lambda r: httpx.Response(200, content=sse(*[delta(str(i)) for i in range(50)], "[DONE]")))
    gen = client.chat_stream([{"role": "user", "content": "x"}])
    assert [next(gen), next(gen)] == ["0", "1"]
    gen.close()  # the viewer pressed stop


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


@pytest.mark.parametrize("text", ["", "no json here", '{"cut": "off by max_tokens', "[unbalanced"])
def test_extract_json_raises_value_error(text):
    with pytest.raises(ValueError):
        client.extract_json(text)


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


def test_circuit_breaker(monkeypatch):
    monkeypatch.setattr(client, "_down_at", -1e9)
    assert not client.down_recently()
    client.mark_down()
    assert client.down_recently() and client.down_recently(5)
    assert not client.down_recently(0)
