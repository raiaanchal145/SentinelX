"""Provider client (AI SOC Analyst milestone) -- one interface, one
implementation, called with plain httpx against the OpenAI
chat-completions schema. NO SDK: httpx is already pinned and the
OpenAI-compatible surface (also spoken by Gemini's compat endpoint and
OpenRouter) keeps a future provider switch a settings change, not a
rewrite (docs/DECISIONS.md, provider decision).

Guarantees:
- timeout on every request (settings.ai_request_timeout_seconds);
- retries with exponential backoff, ONLY on transient failures
  (429 / 5xx / timeouts / transport errors) -- a 400 is never retried;
- token + cost accounting on every call (PRICE_TABLE, per model);
- a hard max-output-tokens cap on every call;
- ONE exception shape for "AI is not available": AiUnavailable. Callers
  (the triage service) treat it as "fall back to rules", never as a
  crash.

Cost caps: the per-organization daily/monthly caps are enforced in
app/ai/service.py, which owns the database sums; client.py provides the
pure comparison (`within_cap`) so the policy is unit-testable without a
DB. A cap breach is NOT an error -- it routes to the fallback path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol

import httpx

from app.config import settings

logger = logging.getLogger("sentinelx.ai")

# Patchable in tests (retry timing must not slow the suite).
_sleep = asyncio.sleep


class AiUnavailable(Exception):
    """AI could not be used at all: no API key, network failure, or a
    non-transient HTTP rejection. Callers must fall back to rules."""


class AiBudgetExceeded(Exception):
    """Raised by service.py when the organization is over its cost cap.
    Never leaves the AI layer -- callers see the fallback, not this."""


# USD per 1M tokens (input, output), list prices (checked 2026-10-02).
# A model missing from the table is billed at the default -- an unknown
# model must not become free accounting.
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
}
DEFAULT_PRICE: tuple[float, float] = (0.15, 0.60)


def price_for(model: str) -> tuple[float, float]:
    return PRICE_TABLE.get(model, DEFAULT_PRICE)


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Dollar cost of one call from reported token counts, rounded to 6
    decimals (the same precision agent_runs.cost_usd stores)."""
    price_in, price_out = price_for(model)
    cost = prompt_tokens / 1_000_000 * price_in + completion_tokens / 1_000_000 * price_out
    return round(cost, 6)


def within_cap(spent_usd: float, cap_usd: float) -> bool:
    """Pure cap check: has `spent` already reached `cap`? The cap is a
    ceiling on TOTAL spend, so a next call is allowed only if it starts
    strictly below the cap."""
    return spent_usd < cap_usd


class AiCallResult:
    """One successful completion with its accounting."""

    __slots__ = ("text", "prompt_tokens", "completion_tokens", "cost_usd", "model", "attempts", "latency_ms")

    def __init__(
        self,
        text: str,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
        attempts: int,
        latency_ms: int,
    ) -> None:
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.model = model
        self.attempts = attempts
        self.latency_ms = latency_ms
        self.cost_usd = estimate_cost_usd(model, prompt_tokens, completion_tokens)

    def to_usage_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "attempts": self.attempts,
            "latency_ms": self.latency_ms,
        }


class AiProvider(Protocol):
    """The one interface every agent stack programs against."""

    async def complete(self, messages: list[dict[str, str]]) -> AiCallResult: ...


class OpenAICompatProvider:
    """OpenAI-compatible chat-completions over httpx."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.base_url = (base_url if base_url is not None else settings.openai_base_url).rstrip("/")
        self.model = model if model is not None else settings.ai_model
        # httpx.MockTransport for tests -- production always passes None.
        self._transport = transport

    async def complete(self, messages: list[dict[str, str]]) -> AiCallResult:
        if not self.api_key:
            # A missing key is a CONFIGURATION state, not an error to
            # spam retries over: raise immediately.
            raise AiUnavailable("no API key configured (openai_api_key is blank)")

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": settings.ai_max_output_tokens,
            "temperature": 0.0,  # reproducibility over creativity (doc §24)
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        started = time.monotonic()
        attempts = 0
        last_error: Exception | None = None
        max_attempts = 1 + max(0, settings.ai_max_retries)
        while attempts < max_attempts:
            attempts += 1
            try:
                async with httpx.AsyncClient(
                    timeout=settings.ai_request_timeout_seconds, transport=self._transport
                ) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", json=payload, headers=headers
                    )
                if response.status_code == 200:
                    data = response.json()
                    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                    usage = data.get("usage") or {}
                    return AiCallResult(
                        text=text or "",
                        prompt_tokens=int(usage.get("prompt_tokens", 0)),
                        completion_tokens=int(usage.get("completion_tokens", 0)),
                        model=self.model,
                        attempts=attempts,
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = AiUnavailable(
                        f"provider returned {response.status_code} (transient)"
                    )
                else:
                    # 400s etc. are permanent -- retrying cannot help.
                    raise AiUnavailable(
                        f"provider rejected the request: HTTP {response.status_code}"
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = AiUnavailable(f"provider unreachable: {type(exc).__name__}")

            if attempts < max_attempts:
                backoff = 0.5 * (2 ** (attempts - 1))
                logger.warning(
                    "ai: attempt %d/%d failed (%s) -- retrying in %.1fs",
                    attempts,
                    max_attempts,
                    last_error,
                    backoff,
                )
                await _sleep(backoff)

        raise AiUnavailable(str(last_error) or "provider failed after retries")


def build_provider() -> AiProvider:
    """The production wiring: OpenAI-compatible, key from settings. A
    blank key still constructs fine -- the call raises AiUnavailable,
    which routes to the fallback instead of crashing the worker."""
    return OpenAICompatProvider()
