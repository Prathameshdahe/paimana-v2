"""Single entry point for talking to the local LM Studio server.

LM Studio serves OpenAI-compatible /chat/completions and /embeddings endpoints. No API key needed locally; we send a
placeholder because some clients require the field.

complete() and call_llm() are the single-turn calls of the brief and the worker cell. chat() takes a message list and
returns the reply; chat_stream() sends the same with "stream": true and yields the content deltas of the server-sent
events as they arrive (lazily: the request starts, and an error surfaces, at the first next(); closing the generator
early closes the connection, and LM Studio stops generating). embed() returns float32 rows, L2-normalised, from the
embedding model in batches. extract_json() reads the first JSON object or array out of a reply (extract_json(text,
dict) an object only): qwen2.5-coder has no native tool calls here, so JSON comes back as text, sometimes fenced or
with prose around it; a reply cut off by max_tokens raises instead of returning one of its parts.

The local model generates one answer at a time (about 4 tokens/s on a laptop), so a generation should go through
LLM_GATE: the caller wraps one call, or the calls of one task, in `with gate(wait_s) as ok:` and does not call when ok
is False (the wait timed out). The gate is not re-entrant, and chat(), chat_stream() and complete() never take it
themselves; backend/brief.py and llm/worker.py do not take it yet (to wrap when the chat is integrated), so until
then a brief can generate alongside a chat answer. A chat request passes chat=True: chat_active() is True while one
holds or waits for the gate. A background take (chat=False) first waits while a chat request is active (at most its
wait_s, or CHAT_YIELD_S when it waits without limit), because a semaphore lets the thread that just released it take
it again before a woken waiter runs; background jobs also check chat_active() between items and pause
(wait_chat_idle), so the person waiting for an answer goes first. Embeddings take no gate (short requests to another
model).

An unreachable server is remembered the way backend/brief.py does it: the caller calls mark_down() after an
LLMConnectionError whose `down` is True (refused, or no connection within CONNECT_TIMEOUT), and down_recently() is True
for DOWN_S seconds after, so the next request does not wait again (on Windows a refused connection takes about 5 s
despite CONNECT_TIMEOUT). An HTTP error, a malformed reply or an LLMTimeoutError (connected, but no answer within the
read timeout) leave `down` False: LM Studio is up, and marking it down would switch the model off for everyone. The
calls never check or set it themselves. A reply that is not streamed arrives only when it is fully generated, so
chat() waits longer the more tokens it allows (_read_timeout); a streamed one only needs each chunk within TIMEOUT.
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
CHAT_YIELD_S = 300.0  # a background gate() without a time limit waits at most this long for chat requests to finish

_transport: httpx.BaseTransport | None = None  # tests put an httpx.MockTransport here
_down_at = -1e9  # time.monotonic() of the last unreachable LM Studio (mark_down)
LLM_GATE = threading.BoundedSemaphore(1)
_chat_lock = threading.Lock()
_chat_n = 0  # chat requests holding or waiting for LLM_GATE


class LLMConnectionError(Exception):
    """LM Studio is unreachable (server not running, wrong port, etc.), answered with an HTTP error or sent a reply
    that is not an OpenAI-shaped completion or embedding. down is True only when no connection could be made: the one
    case for mark_down()."""

    def __init__(self, message: str = "", *, down: bool = False):
        super().__init__(message)
        self.down = down


class LLMTimeoutError(LLMConnectionError):
    """LM Studio took the request but sent nothing within the read timeout: it is up, only slow or busy (down is
    False)."""


class LLMOutputError(Exception):
    """LM Studio responded but the content wasn't valid JSON for the schema."""


# ------------------------------------------------------------------ gate and circuit breaker

@contextmanager
def gate(wait_s: float | None = None, *, chat: bool = False) -> Iterator[bool]:
    """`with gate(wait_s) as ok:` holds LLM_GATE for the block; ok is False when it was not free within wait_s
    seconds (None: wait as long as it takes), and then the block must not generate. chat=True marks a chat request
    (chat_active) while it waits and while it holds the gate; any other take lets active chat requests go first,
    waiting while chat_active() within the same wait_s (at most CHAT_YIELD_S when wait_s is None)."""
    global _chat_n
    if chat:
        with _chat_lock:
            _chat_n += 1
    got = False
    try:
        if not chat and chat_active():
            end = time.monotonic() + (CHAT_YIELD_S if wait_s is None else wait_s)
            while chat_active() and time.monotonic() < end:
                time.sleep(0.02)
            if wait_s is not None:
                wait_s = max(0.0, end - time.monotonic())
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
    """Remember that LM Studio was unreachable just now (after an LLMConnectionError with down True)."""
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
    """The LLMConnectionError for an httpx error: down for a failed connection, LLMTimeoutError for a slow answer."""
    if isinstance(e, httpx.TimeoutException) and not isinstance(e, httpx.ConnectTimeout):
        return LLMTimeoutError(f"LM Studio at {LLM_BASE_URL} did not answer in time ({type(e).__name__})")
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
        return LLMConnectionError(f"LM Studio unreachable at {LLM_BASE_URL}: {e}", down=True)
    detail = str(e)
    if isinstance(e, httpx.HTTPStatusError):
        detail = f"HTTP {e.response.status_code}: {e.response.text[:300]}"
    return LLMConnectionError(f"LM Studio at {LLM_BASE_URL} failed: {detail}")


def _read_timeout(max_tokens: int | None) -> float:
    """Read timeout of a reply that is not streamed: nothing arrives until the whole answer is generated, so it grows
    with max_tokens (2 tokens/s, half the measured rate, plus 30 s for the prompt), never below TIMEOUT."""
    return max(TIMEOUT, 30.0 + (max_tokens or 0) / 2)


def _body(messages: list[dict], max_tokens: int | None, temperature: float, model: str | None,
          stream: bool = False) -> dict:
    body = {"model": model or LLM_CHAT_MODEL, "messages": messages, "temperature": temperature}
    if max_tokens:
        body["max_tokens"] = max_tokens
    if stream:
        body["stream"] = True
    return body


def _completion(body: dict, read_timeout: float = TIMEOUT) -> str:
    try:
        with _http(read_timeout) as c:
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
    when LM Studio is unreachable or answers with an error, LLMTimeoutError when the whole reply takes longer than
    _read_timeout(max_tokens)."""
    return _completion(_body(messages, max_tokens, temperature, model), _read_timeout(max_tokens))


def _sse_data(line: str) -> str | None:
    """The payload of one server-sent-event 'data:' line; None for comments, other fields and blank lines."""
    if not line.startswith("data:"):
        return None
    return line[5:].strip()


_LINE_END = re.compile(r"\r\n|\r|\n")


def _lines(parts: Iterator[str]) -> Iterator[str]:
    """The lines of a decoded text stream, split at CR, LF or CRLF only (the server-sent-events line ends). httpx's
    iter_lines() uses str.splitlines(), which also splits at U+2028, U+2029, U+0085 and a few control characters,
    and JSON may carry those raw inside a string: the delta would be cut in two and lost."""
    buf = ""
    for part in parts:
        buf += part
        *lines, buf = _LINE_END.split(buf)
        yield from lines
    if buf:
        yield buf


def _not_a_chunk(data: str) -> LLMConnectionError:
    return LLMConnectionError(f"LM Studio sent a stream event that is not a chat completion chunk: {data[:300]}")


def chat_stream(messages: list[dict], *, max_tokens: int = 400, temperature: float = 0.2,
                model: str | None = None) -> Iterator[str]:
    """chat() streamed: yields the content deltas until 'data: [DONE]' (or the end of the stream after a choice with
    a finish_reason). LLMConnectionError on an HTTP error (raised at the first next()), a dropped connection, an
    error event, an event that is not a completion chunk, or a stream that ends before [DONE] and any finish_reason
    (a truncated answer must not pass as a whole one)."""
    try:
        with _http() as c, c.stream("POST", "/chat/completions",
                                    json=_body(messages, max_tokens, temperature, model, stream=True)) as resp:
            if resp.is_error:
                resp.read()
                resp.raise_for_status()
            finished = False
            for line in _lines(resp.iter_text()):
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
                choices = chunk.get("choices") or []
                if not isinstance(choices, list):
                    raise _not_a_chunk(data)
                for choice in choices:
                    delta = (choice.get("delta") or {}) if isinstance(choice, dict) else None
                    if not isinstance(delta, dict):
                        raise _not_a_chunk(data)
                    text = delta.get("content")
                    if text and isinstance(text, str):
                        yield text
                    finished = finished or bool(choice.get("finish_reason"))
            if not finished:
                raise LLMConnectionError("LM Studio stream ended before [DONE]: the answer may be cut off")
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


_NOT_JSON = object()


def _loads(span: str):
    for cand in (span, TRAILING_COMMA.sub(r"\1", span)):
        try:
            return json.loads(cand)
        except ValueError:
            pass
    return _NOT_JSON


def _plain_list(v) -> bool:
    """A list of plain values only: in prose, '[1]' is a citation and '[2024]' a year, not the answer."""
    return isinstance(v, list) and not any(isinstance(x, (dict, list)) for x in v)


def extract_json(text: str, want: type | None = None) -> dict | list:
    """The first JSON object or array in an LLM reply: inside a ``` fence first, else anywhere in the text, prose
    around it ignored; a trailing comma before a closing bracket is forgiven. want=dict or want=list takes only that
    type (a caller that needs a list of plain values should ask for it fenced or inside an object: prose brackets
    look the same). With want None, a list of plain values is taken only when no object or nested list follows it
    in its block (a fence, else the whole text). A bracket that never closes (a reply cut off by max_tokens) ends the
    search in its block: nothing inside it is taken, so a truncated plan never comes back as one of its parts.
    json.JSONDecodeError (a ValueError) when there is none."""
    if want not in (None, dict, list):
        raise TypeError(f"want must be dict, list or None, not {want!r}")
    text = text or ""
    for block in [m.group(1) for m in FENCE.finditer(text)] + [text]:
        i, plain = 0, _NOT_JSON
        while True:
            starts = [p for p in (block.find("{", i), block.find("[", i)) if p >= 0]
            if not starts:
                break
            start = min(starts)
            end = _close(block, start)
            if end is None:  # cut off: what is inside is part of it, and a list before it is prose
                plain = _NOT_JSON
                break
            v = _loads(block[start:end + 1])
            i = end + 1  # past this span, JSON or prose in brackets
            if v is _NOT_JSON or (want is not None and not isinstance(v, want)):
                continue
            if want is None and _plain_list(v):
                plain = v if plain is _NOT_JSON else plain
                continue
            return v
        if plain is not _NOT_JSON:
            return plain
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
        return response_model(**extract_json(raw, dict))
    except (json.JSONDecodeError, ValidationError, TypeError) as first_err:
        retry_prompt = (
            f"{user_prompt}\n\nYour previous reply failed to parse: {first_err}\n"
            f"Previous reply was: {raw}\nReturn ONLY corrected JSON matching the schema."
        )
        raw2 = _post(full_system, retry_prompt)
        try:
            return response_model(**extract_json(raw2, dict))
        except (json.JSONDecodeError, ValidationError, TypeError) as second_err:
            raise LLMOutputError(
                f"LM Studio returned invalid JSON twice. Last error: {second_err}. Last raw: {raw2}"
            ) from second_err
