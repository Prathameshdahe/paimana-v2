"""Single entry point for talking to the local LM Studio server.

LM Studio serves an OpenAI-compatible /chat/completions endpoint. No API key
needed locally; we send a placeholder because some clients require the field.
"""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen/qwen2.5-coder-14b")
TIMEOUT = 120.0  # local 14B model can be slow


class LLMConnectionError(Exception):
    """LM Studio is unreachable (server not running, wrong port, etc.)."""


class LLMOutputError(Exception):
    """LM Studio responded but the content wasn't valid JSON for the schema."""


def _extract_json(text: str) -> str:
    """Best-effort strip of markdown code fences some models add anyway."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _post(system_prompt: str, user_prompt: str) -> str:
    try:
        resp = httpx.post(
            f"{LLM_BASE_URL}/chat/completions",
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            },
            headers={"Authorization": "Bearer not-needed"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise LLMConnectionError(f"LM Studio unreachable at {LLM_BASE_URL}: {e}") from e
    return resp.json()["choices"][0]["message"]["content"]


def call_llm(system_prompt: str, user_prompt: str, response_model: type[BaseModel]) -> BaseModel:
    """POST to LM Studio, demand JSON matching response_model, validate, retry once on failure."""
    schema_hint = (
        f"\n\nRespond with ONLY a single JSON object, no prose, no markdown fences, "
        f"matching this JSON schema exactly:\n{json.dumps(response_model.model_json_schema())}"
    )
    full_system = system_prompt + schema_hint

    raw = _post(full_system, user_prompt)
    try:
        return response_model(**json.loads(_extract_json(raw)))
    except (json.JSONDecodeError, ValidationError, TypeError) as first_err:
        retry_prompt = (
            f"{user_prompt}\n\nYour previous reply failed to parse: {first_err}\n"
            f"Previous reply was: {raw}\nReturn ONLY corrected JSON matching the schema."
        )
        raw2 = _post(full_system, retry_prompt)
        try:
            return response_model(**json.loads(_extract_json(raw2)))
        except (json.JSONDecodeError, ValidationError, TypeError) as second_err:
            raise LLMOutputError(
                f"LM Studio returned invalid JSON twice. Last error: {second_err}. Last raw: {raw2}"
            ) from second_err
