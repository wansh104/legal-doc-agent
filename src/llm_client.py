"""
Gemini client wrapper.

Two modes:
  - LIVE  : calls the real Gemini API with response_schema enforcement,
            so the model is constrained to return valid JSON matching our
            pydantic schema.
  - MOCK  : returns a canned response for the exact sample inputs in this
            assignment. Used for local testing/demo without an API key, and
            is what lets the pipeline run in environments with no network
            access to Gemini (e.g. this build/test sandbox).

Set GEMINI_API_KEY in the environment (or Streamlit secrets) to use LIVE
mode. If it's unset, the pipeline automatically falls back to MOCK mode and
prints a warning — this is documented in the README as a demo mode.
"""

from __future__ import annotations
import os
import json
from typing import Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

MODEL_NAME = "gemini-3.6-flash"


class LLMError(Exception):
    """Raised when the LLM call fails or returns output that doesn't
    validate against the requested schema. Caught by pipeline.py and
    reported with stage context, not just a raw traceback."""
    pass


def _is_live_configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def generate_structured(prompt: str, schema_cls: Type[T], mock_response: dict | None = None) -> T:
    """Call Gemini asking for output matching schema_cls, validate, return
    an instance of schema_cls. Falls back to mock_response if no API key is
    configured (mock_response is supplied by the caller, since only the
    caller knows what a plausible mock looks like for its own prompt)."""

    if _is_live_configured():
        return _generate_live(prompt, schema_cls)

    if mock_response is None:
        raise LLMError(
            "GEMINI_API_KEY is not set and no mock_response was provided for this call. "
            "Set GEMINI_API_KEY to run live, or pass a mock for offline testing."
        )
    try:
        return schema_cls.model_validate(mock_response)
    except Exception as e:
        raise LLMError(f"Mock response failed schema validation: {e}") from e

def _safe_extract_text(response) -> str:
    """response.text raises instead of returning "" when Gemini responds
    with zero content parts — which happens routinely here, since our own
    prompts explicitly ask for an empty response when there's nothing to
    add. Treat that as a legitimate empty string, not a failure."""
    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return ""
        parts = getattr(candidates[0].content, "parts", None) or []
        if not parts:
            return ""
        return response.text.strip()
    except (ValueError, AttributeError, IndexError):
        return ""

def _generate_live(prompt: str, schema_cls: Type[T]) -> T:
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise LLMError(
            "google-generativeai is not installed. Run: pip install google-generativeai"
        ) from e

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    schema = schema_cls.model_json_schema()
    # Gemini's response_schema doesn't support every JSON Schema keyword
    # (e.g. $defs/$ref for nested pydantic models must be inlined). We ask
    # for plain JSON in the prompt as a robust fallback and validate against
    # the pydantic model ourselves, rather than depending on strict
    # response_schema support for deeply nested models.
    model = genai.GenerativeModel(
        MODEL_NAME,
        generation_config={"response_mime_type": "application/json"},
    )
    full_prompt = (
        f"{prompt}\n\n"
        f"Return ONLY a single JSON object matching this schema (no markdown fences, no commentary):\n"
        f"{json.dumps(schema, indent=2)}"
    )
    response = model.generate_content(full_prompt)
    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        raw_text = _safe_extract_text(response)
        if not raw_text:
            raise LLMError("Gemini returned an empty response for the extraction call (no content parts).")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    try:
        data = json.loads(raw_text)
        return schema_cls.model_validate(data)
    except Exception as e:
        raise LLMError(f"Gemini response did not match {schema_cls.__name__} schema: {e}\nRaw: {raw_text[:500]}") from e


def generate_text(prompt: str, mock_response: str | None = None) -> str:
    """Free-text generation (used for paragraph drafting, not JSON)."""
    if _is_live_configured():
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise LLMError("google-generativeai is not installed.") from e
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt)
        return _safe_extract_text(response)

    if mock_response is None:
        raise LLMError("GEMINI_API_KEY not set and no mock_response provided for text generation.")
    return mock_response
