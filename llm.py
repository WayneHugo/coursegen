"""Thin wrapper over the Anthropic SDK: structured calls and web research calls."""

from __future__ import annotations

import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from coursegen.models import Dossier, Source

T = TypeVar("T", bound=BaseModel)

MODEL = os.environ.get("COURSEGEN_MODEL", "claude-opus-5-5")
# Server-side refusal fallback: a declined request is re-run on a fallback model
# chosen by refusal category. Set COURSEGEN_NO_FALLBACK=1 to turn it off.
USE_FALLBACK = not os.environ.get("COURSEGEN_NO_FALLBACK")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_CONTINUATIONS = 5


class LLMError(RuntimeError):
    pass


def _fallback_kwargs() -> dict:
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"} if USE_FALLBACK else {}


def _check_stop(response) -> None:
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise LLMError(f"model declined: {getattr(details, 'explanation', '') or 'no details'}")
    if response.stop_reason == "max_tokens":
        raise LLMError("response hit max_tokens; output was truncated")


class LLM:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model

    def structured(self, system: str, prompt: str, schema: type[T], effort: str = "medium") -> T:
        """One call whose answer is validated against a pydantic schema."""
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": effort},
                **_fallback_kwargs(),
            ) as stream:
                response = stream.get_final_message()
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        _check_stop(response)
        if response.parsed_output is None:
            raise LLMError("model returned no parseable output")
        return response.parsed_output

    def research(self, system: str, prompt: str, angle: str, query: str, max_searches: int = 5) -> Dossier:
        """Let the model search and read the web, then write a research dossier."""
        tools = [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_searches},
        ]
        messages: list[dict] = [{"role": "user", "content": prompt}]
        content: list = []
        for _ in range(MAX_CONTINUATIONS + 1):
            try:
                with self.client.beta.messages.stream(
                    model=self.model,
                    max_tokens=64000,
                    system=system,
                    tools=tools,
                    messages=messages,
                    output_config={"effort": "medium"},
                    **_fallback_kwargs(),
                ) as stream:
                    response = stream.get_final_message()
            except anthropic.APIStatusError as e:
                raise LLMError(f"API error {e.status_code}: {e.message}") from e
            content.extend(response.content)
            if response.stop_reason != "pause_turn":
                break
            # Server-side tool loop paused: resend so far, and the server resumes.
            messages = [messages[0], {"role": "assistant", "content": content}]
        _check_stop(response)
        return Dossier(angle=angle, query=query, text=_text_of(content), sources=_sources_of(content))


def _text_of(content: list) -> str:
    return "\n".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


def _sources_of(content: list) -> list[Source]:
    """Collect every URL the model searched, fetched, or cited, de-duplicated."""
    seen: dict[str, Source] = {}

    def add(url: str | None, title: str | None) -> None:
        if url and url not in seen:
            seen[url] = Source(url=url, title=title or "")

    for block in content:
        btype = getattr(block, "type", None)
        if btype == "web_search_tool_result":
            results = block.content
            if isinstance(results, list):  # an error is a single object, not a list
                for r in results:
                    add(getattr(r, "url", None), getattr(r, "title", None))
        elif btype == "web_fetch_tool_result":
            add(getattr(block.content, "url", None), None)
        elif btype == "text":
            for c in getattr(block, "citations", None) or []:
                add(getattr(c, "url", None), getattr(c, "title", None))
    return list(seen.values())
