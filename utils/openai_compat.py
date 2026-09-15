"""Compatibility helpers for OpenAI Chat Completions models."""

import os
import re


_GPT5_MODEL_RE = re.compile(r"^gpt-5(?:$|[-.])", re.IGNORECASE)
_GPT5_REASONING_EFFORTS = {"minimal", "low", "medium", "high"}


def is_gpt5_model(model: str) -> bool:
    """Return whether ``model`` belongs to the requested GPT-5 family."""
    return bool(_GPT5_MODEL_RE.match((model or "").strip()))


def reasoning_effort_from_env(name: str, default: str) -> str:
    """Read and validate a GPT-5 reasoning effort setting."""
    value = os.getenv(name, default).strip().lower()
    if value not in _GPT5_REASONING_EFFORTS:
        allowed = ", ".join(sorted(_GPT5_REASONING_EFFORTS))
        raise ValueError(f"{name} phai la mot trong cac gia tri: {allowed}")
    return value


def build_chat_completion_kwargs(
    *,
    model: str,
    messages: list,
    max_tokens: int,
    temperature: float,
    reasoning_effort: str | None = None,
) -> dict:
    """Build model-aware kwargs while preserving the GPT-4o contract."""
    kwargs = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if is_gpt5_model(model):
        kwargs["max_completion_tokens"] = max_tokens
        if reasoning_effort is not None:
            if reasoning_effort not in _GPT5_REASONING_EFFORTS:
                raise ValueError("GPT-5 reasoning effort khong hop le")
            kwargs["reasoning_effort"] = reasoning_effort
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature
    return kwargs
