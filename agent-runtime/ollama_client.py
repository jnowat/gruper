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
import time
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


class OllamaError(Exception):
    """A classified Ollama failure.

    `code` is machine-readable and travels in the task's error payload all the
    way to the Console, so the UI can say exactly what went wrong instead of a
    generic "couldn't respond":
      ollama_unreachable — TCP connect failed/timed out (Ollama not running?)
      model_not_found    — Ollama is up but doesn't have the requested model
      ollama_timeout     — Ollama accepted the request but stopped responding
      ollama_error       — anything else (HTTP 5xx, protocol errors, …)
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OllamaClient:
    # connect is deliberately SHORT: "Ollama isn't running" must fail in
    # seconds, not hang until a generic timeout — a dead endpoint used to be
    # indistinguishable from a slow model. read is deliberately LONG: it is
    # the gap between streamed chunks, and a cold model can take a minute or
    # more to load before the first token on modest Windows hardware.
    def __init__(self, base_url: str, connect_timeout_s: float = 5.0, read_timeout_s: float = 240.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=connect_timeout_s, read=read_timeout_s, write=30.0, pool=10.0
        )

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
        Raises OllamaError with a machine-readable code on any failure.
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {**_DEFAULT_OPTIONS, **(options or {})},
        }
        url = f"{self._base_url}/api/chat"
        started = time.monotonic()
        logger.info(
            "Ollama request starting: model=%s url=%s messages=%d", model, url, len(messages)
        )
        chunks = 0
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode(errors="replace")[:500]
                        raise self._classify_http_error(resp.status_code, body, model)
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            logger.debug("Non-JSON line from Ollama: %r", line)
                            continue
                        # Ollama reports mid-stream errors as {"error": "..."}
                        if chunk.get("error"):
                            raise self._classify_http_error(200, str(chunk["error"]), model)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            chunks += 1
                            yield content
                        if chunk.get("done"):
                            if stats is not None:
                                for k in self._STAT_FIELDS:
                                    if chunk.get(k) is not None:
                                        stats[k] = chunk[k]
                            break
            logger.info(
                "Ollama request finished: model=%s chunks=%d duration_ms=%d",
                model, chunks, int((time.monotonic() - started) * 1000),
            )
        except OllamaError as exc:
            logger.error(
                "Ollama request failed: model=%s url=%s code=%s detail=%s",
                model, url, exc.code, exc,
            )
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            logger.error("Ollama unreachable: url=%s (%s)", url, exc)
            raise OllamaError(
                "ollama_unreachable",
                f"Can't reach Ollama at {self._base_url} — is it running?",
            ) from exc
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            logger.error(
                "Ollama timed out: model=%s url=%s after %d chunks (%s)", model, url, chunks, exc
            )
            raise OllamaError(
                "ollama_timeout",
                f"Ollama stopped responding while running {model} — the model may be too "
                "large for this machine, or Ollama may be overloaded.",
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("Ollama request error: model=%s url=%s (%s)", model, url, exc)
            raise OllamaError("ollama_error", f"Ollama request failed: {exc}") from exc

    def _classify_http_error(self, status_code: int, body: str, model: str) -> OllamaError:
        """Turn an Ollama error response into a classified OllamaError."""
        lowered = body.lower()
        if status_code == 404 or "not found" in lowered:
            return OllamaError(
                "model_not_found",
                f'The model "{model}" isn\'t installed in Ollama any more. '
                f'Run "ollama pull {model}", or change this agent\'s model.',
            )
        return OllamaError(
            "ollama_error",
            f"Ollama returned an error (HTTP {status_code}): {body or 'no detail'}",
        )

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
