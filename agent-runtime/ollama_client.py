"""
Thin async wrapper around the Ollama REST API.

Parameter names mirror Gruper core's per-agent config conventions so that
task payloads authored by the Manager Console round-trip cleanly.

  Core name       Ollama option field   Notes
  --------------- --------------------- -------
  temperature     temperature           0–1
  top_p           top_p                 0–1
  top_k           top_k                 1–100
  repeat_penalty  repeat_penalty        0.5–2
  max_tokens      num_predict           128–8192
  context_length  num_ctx               512–16384
  seed            seed                  optional
"""

import json
import logging
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_OPTIONS: dict = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "num_predict": 2048,
    "num_ctx": 4096,
}


class OllamaClient:
    def __init__(self, base_url: str, timeout_s: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    # Fields on Ollama's final (done) chunk we surface for accurate metrics.
    # eval_count = output tokens generated; eval_duration = generation time in
    # nanoseconds; prompt_eval_count = input tokens. These are the real counts,
    # not the streamed-chunk count we previously reported as "tokens".
    _STAT_FIELDS = (
        "eval_count",
        "eval_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "total_duration",
    )

    async def chat(
        self,
        messages: list[dict],
        model: str,
        options: dict | None = None,
        stats: dict | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream /api/chat response chunks.

        Yields individual content strings as they arrive from Ollama. If a
        mutable `stats` dict is passed, it is populated from Ollama's final
        "done" chunk with real token/timing counts (eval_count etc.) — pass a
        fresh dict per call, since one client instance serves concurrent tasks.
        Raises httpx.HTTPStatusError on non-2xx responses.
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {**_DEFAULT_OPTIONS, **(options or {})},
        }
        url = f"{self._base_url}/api/chat"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug("Non-JSON line from Ollama: %r", line)
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        if stats is not None:
                            for k in self._STAT_FIELDS:
                                if chunk.get(k) is not None:
                                    stats[k] = chunk[k]
                        break

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/api/tags")
            resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
