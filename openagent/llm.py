"""OpenRouter chat client. Preserves reasoning fields the model needs on the next turn."""

from __future__ import annotations

import logging

import httpx

from openagent.config import Settings

log = logging.getLogger("openagent.llm")

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    pass


class OpenRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def complete(self, messages: list[dict], tools: list[dict]) -> tuple[dict, dict]:
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens": self.settings.max_output_tokens,
        }
        if self.settings.provider_sort:
            payload["provider"] = {"sort": self.settings.provider_sort}
        response = await self._post(payload)
        if response.status_code == 400 and _should_retry_without_provider(response.text, payload):
            log.warning("Retrying without provider sort: %s", response.text[:300])
            payload.pop("provider", None)
            response = await self._post(payload)
        if response.status_code == 400 and "max_completion_tokens" in response.text and "max_tokens" in payload:
            limit = payload.pop("max_tokens")
            payload["max_completion_tokens"] = limit
            response = await self._post(payload)
        if response.status_code == 400 and "parallel_tool_calls" in response.text and "parallel_tool_calls" in payload:
            payload.pop("parallel_tool_calls", None)
            response = await self._post(payload)
        if response.status_code >= 400:
            raise LLMError(f"OpenRouter {response.status_code}: {response.text[:800]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("OpenRouter returned a response that was not JSON.") from exc
        choices = body.get("choices") or []
        if not choices:
            raise LLMError("OpenRouter returned no choices.")
        message = choices[0].get("message") or {}
        if not message.get("reasoning_details") and choices[0].get("reasoning_details"):
            message["reasoning_details"] = choices[0]["reasoning_details"]
        usage = body.get("usage") or {}
        return message, usage

    async def _post(self, payload: dict) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost/openagent",
            "X-Title": "OpenAgent",
        }
        try:
            response = await self._client.post(API_URL, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach OpenRouter: {exc}") from exc
        if response.status_code in {429, 502, 503}:
            log.warning("OpenRouter %s, retrying once", response.status_code)
            try:
                response = await self._client.post(API_URL, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                raise LLMError(f"Could not reach OpenRouter: {exc}") from exc
        return response


def _should_retry_without_provider(body: str, payload: dict) -> bool:
    if "provider" not in payload:
        return False
    lowered = body.lower()
    return "provider" in lowered or "sort" in lowered or "exacto" in lowered
