"""Single entry point for talking to the local LM Studio server.

LM Studio serves OpenAI-compatible /chat/completions and /embeddings endpoints. No API key needed locally; we send a
placeholder because some clients require the field.

complete() and call_llm() are the single-turn calls of the brief and the worker cell. chat() takes a message list and
returns the reply; chat_stream() sends the same with "stream": true and yields the content deltas of the server-sent
events as they arrive (lazily: the request starts, and an error surfaces, at the first next(); closing the generator
early closes the connection, and LM Studio stops generating). embed() returns float32 rows, L2-normalised, from the
embedding model in batches. extract_json() reads the first JSON object or array out of a reply: qwen2.5-coder has no
native tool calls here, so JSON comes back as text, sometimes fenced or with prose around it.

The local model generates one answer at a time (about 4 tokens/s on a laptop), so every generation goes through
LLM_GATE: the caller wraps one call, or the calls of one task, in `with gate(wait_s) as ok:` and does not call when ok
is False (the wait timed out). The gate is not re-entrant, and chat(), chat_stream() and complete() never take it
themselves. A chat request passes chat=True: chat_active() is True while one holds or waits for the gate, and
background jobs check it between items and pause (wait_chat_idle), so the person waiting for an answer goes first.
Embeddings take no gate (short requests to another model).

An unreachable server is remembered the way backend/brief.py does it: the caller calls mark_down() after an
LLMConnectionError, and down_recently() is True for DOWN_S seconds after, so the next request does not wait again (on
Windows a refused connection takes about 5 s despite CONNECT_TIMEOUT). The calls never check it themselves.
"""
import json
import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen/qwen2.5-coder-14b")
LLM_CHAT_MODEL = os.environ.get("LLM_CHAT_MODEL") or LLM_MODEL
LLM_EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")
TIMEOUT = 120.0  # local 14B model can be slow (a streamed reply: the longest gap between two chunks)
CONNECT_TIMEOUT = 3.0  # but a server that is not running fails fast
EMBED_TIMEOUT = 60.0
DOWN_S = 30

_transport: httpx.BaseTransport | None = None  # tests put an httpx.MockTransport here
_down_at = -1e9  # time.monotonic() of the last unreachable LM Studio (mark_down)
LLM_GATE = threading.BoundedSemaphore(1)
_chat_lock = threading.Lock()
_chat_n = 0  # chat requests holding or waiting for LLM_GATE


class LLMConnectionError(Exception):
    """LM Studio is unreachable (server not running, wrong port, etc.), answered with an HTTP error or sent a reply
    that is not an OpenAI-shaped completion or embedding."""


class LLMOutputError(Exception):
    """LM Studio responded but the content wasn't valid JSON for the schema."""


# ------------------------------------------------------------------ gate and circuit breaker

@contextmanager
def gate(wait_s: float | None = None, *, chat: bool = False) -> Iterator[bool]:
    """`with gate(wait_s) as ok:` holds LLM_GATE for the block; ok is False when it was not free within wait_s
    seconds (None: wait as long as it takes), and then the block must not generate. chat=True marks a chat request
    (chat_active) while it waits and while it holds the gate."""
    global _chat_n
    if chat:
        with _chat_lock:
            _chat_n += 1
    got = False
    try:
        got = LLM_GATE.acquire(timeout=wait_s)
        yield got
    finally:
        if got:
            LLM_GATE.release()
        if chat:
            with _chat_lock:
                _chat_n -= 1


def chat_active() -> bool:
    """True while a chat request holds or waits for LLM_GATE; background jobs pause between items."""
    return _chat_n > 0


def wait_chat_idle(max_s: float = 300.0, poll_s: float = 0.5) -> bool:
    """Sleep while chat_active(), at most max_s seconds; True once no chat request is active."""
    end = time.monotonic() + max_s
    while chat_active():
        if time.monotonic() >= end:
            return False
        time.sleep(poll_s)
    return True


def mark_down() -> None:
    """Remember that LM Studio was unreachable just now (after an LLMConnectionError)."""
    global _down_at
    _down_at = time.monotonic()


def down_recently(s: float = DOWN_S) -> bool:
    """True when LM Studio was marked unreachable in the last s seconds."""
    return time.monotonic() - _down_at < s


# ------------------------------------------------------------------ HTTP

def _http(read_timeout: float = TIMEOUT) -> httpx.Client:
    transport = _transport
    if transport is None and httpx.URL(LLM_BASE_URL).host == "localhost":
        # Windows tries ::1 first and LM Studio listens on IPv4 only: about 2 s lost per request otherwise
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
    return httpx.Client(base_url=LLM_BASE_URL, transport=transport,
                        headers={"Authorization": "Bearer not-needed"},
                        timeout=httpx.Timeout(read_timeout, connect=CONNECT_TIMEOUT))


def _unreachable(e: Exception) -> LLMConnectionError:
    detail = str(e)
    if isinstance(e, httpx.HTTPStatusError):
        detail = f"HTTP {e.response.status_code}: {e.response.text[:300]}"
    return LLMConnectionError(f"LM Studio unreachable at {LLM_BASE_URL}: {detail}")


def _body(messages: list[dict], max_tokens: int | None, temperature: float, model: str | None,
          stream: bool = False) -> dict:
    body = {"model": model or LLM_CHAT_MODEL, "messages": messages, "temperature": temperature}
    if max_tokens:
        body["max_tokens"] = max_tokens
    if stream:
        body["stream"] = True
    return body


def _completion(body: dict) -> str:
    try:
        with _http() as c:
            resp = c.post("/chat/completions", json=body)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"] or ""
    except httpx.HTTPError as e:
        raise _unreachable(e) from e
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise LLMConnectionError(f"LM Studio sent a reply that is not a chat completion: {e!r}") from e


def _post(system_prompt: str, user_prompt: str) -> str:
    return _completion({"model": LLM_MODEL, "temperature": 0.2,
                        "messages": [{"role": "system", "content": system_prompt},
                                     {"role": "user", "content": user_prompt}]})


def complete(system_prompt: str, user_prompt: str) -> str:
    """Plain-text chat completion (no JSON schema); raises LLMConnectionError when LM Studio is unreachable."""
    return _post(system_prompt, user_prompt)


def chat(messages: list[dict], *, max_tokens: int = 400, temperature: float = 0.2, model: str | None = None) -> str:
    """The reply to an OpenAI message list ({'role': 'system'|'user'|'assistant', 'content'}); LLMConnectionError
    when LM Studio is unreachable or answers with an error."""
    return _completion(_body(messages, max_tokens, temperature, model))


def _sse_data(line: str) -> str | None:
    """The payload of one server-sent-event 'data:' line; None for comments, other fields and blank lines."""
    if not line.startswith("data:"):
        return None
    return line[5:].strip()


def chat_stream(messages: list[dict], *, max_tokens: int = 400, temperature: float = 0.2,
                model: str | None = None) -> Iterator[str]:
    """chat() streamed: yields the content deltas until 'data: [DONE]' or the end of the stream. LLMConnectionError on
    an HTTP error (raised at the first next()), a dropped connection or an error event."""
    try:
        with _http() as c, c.stream("POST", "/chat/completions",
                                    json=_body(messages, max_tokens, temperature, model, stream=True)) as resp:
            if resp.is_error:
                resp.read()
                resp.raise_for_status()
            for line in resp.iter_lines():
                data = _sse_data(line)
                if not data:
                    continue
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue  # a keep-alive or a line we do not know; the deltas are JSON
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    raise LLMConnectionError(f"LM Studio stream error: {str(chunk['error'])[:300]}")
                for choice in chunk.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield text
    except httpx.HTTPError as e:
        raise _unreachable(e) from e


def embed(texts: list[str], *, model: str | None = None, batch: int = 64) -> np.ndarray:
    """(len(texts), dim) float32, each row L2-normalised, from the embedding model in requests of `batch` texts;
    LLMConnectionError when LM Studio is unreachable, fails or returns the wrong number of vectors."""
    parts = []
    with _http(EMBED_TIMEOUT) as c:
        for i in range(0, len(texts), batch):
            chunk = [t if t.strip() else " " for t in texts[i:i + batch]]  # an empty input is a 400
            try:
                resp = c.post("/embeddings", json={"model": model or LLM_EMBED_MODEL, "input": chunk})
                resp.raise_for_status()
                rows = [d["embedding"] for d in sorted(resp.json()["data"], key=lambda d: d["index"])]
                part = np.asarray(rows, dtype=np.float32)
            except httpx.HTTPError as e:
                raise _unreachable(e) from e
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise LLMConnectionError(f"LM Studio sent a reply that is not an embedding list: {e!r}") from e
            if part.ndim != 2 or len(part) != len(chunk) or (parts and part.shape[1] != parts[0].shape[1]):
                raise LLMConnectionError(f"LM Studio returned {part.shape} embeddings for {len(chunk)} texts")
            parts.append(part)
    if not parts:
        return np.zeros((0, 0), np.float32)
    m = np.vstack(parts)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms > 0, norms, 1)


# ------------------------------------------------------------------ JSON replies

FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n?(.*?)```", re.S)
TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _close(s: str, start: int) -> int | None:
    """Index of the bracket that closes the one at start (brackets inside JSON strings do not count), or None."""
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return i
    return None


def extract_json(text: str) -> dict | list:
    """The first JSON object or array in an LLM reply: inside a ``` fence first, else anywhere in the text, prose
    around it ignored; a trailing comma before a closing bracket is forgiven. json.JSONDecodeError (a ValueError) when
    there is none."""
    text = text or ""
    for block in [m.group(1) for m in FENCE.finditer(text)] + [text]:
        i = 0
        while True:
            starts = [p for p in (block.find("{", i), block.find("[", i)) if p >= 0]
            if not starts:
                break
            start = min(starts)
            end = _close(block, start)
            if end is None:
                i = start + 1
                continue
            span = block[start:end + 1]
            for cand in (span, TRAILING_COMMA.sub(r"\1", span)):
                try:
                    return json.loads(cand)
                except ValueError:
                    pass
            i = end + 1  # a bracketed span that is not JSON (prose in brackets): look after it
    raise json.JSONDecodeError("no JSON object or array in the reply", text, 0)


def call_llm(system_prompt: str, user_prompt: str, response_model: type[BaseModel]) -> BaseModel:
    """POST to LM Studio, demand JSON matching response_model, validate, retry once on failure."""
    schema_hint = (
        f"\n\nRespond with ONLY a single JSON object, no prose, no markdown fences, "
        f"matching this JSON schema exactly:\n{json.dumps(response_model.model_json_schema())}"
    )
    full_system = system_prompt + schema_hint

    raw = _post(full_system, user_prompt)
    try:
        return response_model(**extract_json(raw))
    except (json.JSONDecodeError, ValidationError, TypeError) as first_err:
        retry_prompt = (
            f"{user_prompt}\n\nYour previous reply failed to parse: {first_err}\n"
            f"Previous reply was: {raw}\nReturn ONLY corrected JSON matching the schema."
        )
        raw2 = _post(full_system, retry_prompt)
        try:
            return response_model(**extract_json(raw2))
        except (json.JSONDecodeError, ValidationError, TypeError) as second_err:
            raise LLMOutputError(
                f"LM Studio returned invalid JSON twice. Last error: {second_err}. Last raw: {raw2}"
            ) from second_err
