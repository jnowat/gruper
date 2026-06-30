"""
Mock Ollama server for WP-06 end-to-end relay validation.

Implements just enough of the Ollama REST surface that the agent runtime's
`OllamaClient` exercises:

  GET  /api/tags   → advertise one model
  POST /api/chat   → stream NDJSON chat chunks (the real Ollama streaming shape)

This lets the full relay (console → orchestrator → agent → "Ollama" → back) run
without a GPU or a real model download. Inference is deterministic so the
validation harness can assert on the exact output text.

Behaviour is driven by the prompt so a single mock can serve both the fast happy
path and the slow path needed to kill an agent mid-task:

  prompt contains "[SLOW]" → 20 chunks at 200 ms each (~4 s) so the harness has
                             a wide window to SIGKILL the agent mid-stream.
  otherwise               → 6 chunks at ~80 ms each (~0.5 s) for the happy path.

Run standalone:  python tests/e2e/mock_ollama.py 11500
"""

import asyncio
import json
import sys

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="Mock Ollama (WP-06)")

_FAST_CHUNKS = ["Gruper ", "relay ", "validated ", "end ", "to ", "end."]
_SLOW_CHUNKS = [f"tok{i} " for i in range(20)]


def _last_user_content(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


@app.get("/api/tags")
async def tags() -> dict:
    return {"models": [{"name": "llama3.1:8b"}, {"name": "mock:latest"}]}


@app.post("/api/chat")
async def chat(req: Request) -> StreamingResponse:
    body = await req.json()
    model = body.get("model", "llama3.1:8b")
    messages = body.get("messages", [])
    prompt = _last_user_content(messages)

    slow = "[SLOW]" in prompt
    chunks = _SLOW_CHUNKS if slow else _FAST_CHUNKS
    delay = 0.20 if slow else 0.08

    async def gen():
        for c in chunks:
            await asyncio.sleep(delay)
            yield json.dumps({
                "model": model,
                "message": {"role": "assistant", "content": c},
                "done": False,
            }) + "\n"
        # Final done frame, mirroring Ollama's terminal message.
        yield json.dumps({
            "model": model,
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
        }) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


if __name__ == "__main__":
    import uvicorn

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 11500
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
