#!/opt/hermes/.venv/bin/python
"""Expose Ollama's native chat API as a small OpenAI-compatible endpoint."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, AsyncIterator
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL", "http://192.168.1.2:11434"
).rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-4b-gpu:latest")
REQUEST_TIMEOUT = float(os.environ.get("OLLAMA_BRIDGE_TIMEOUT", "180"))
KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "24h")
THINK = os.environ.get("OLLAMA_THINK", "false").lower() in {"1", "true", "yes"}

app = FastAPI(title="Hermes Ollama OpenAI Bridge", docs_url=None, redoc_url=None)


def final_content(content: str) -> str:
    """Remove Qwen reasoning wrappers when local thinking is disabled."""
    if THINK:
        return content
    if "</think>" in content:
        content = content.rsplit("</think>", 1)[1]
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    return content.lstrip()


def openai_tool_calls(raw_calls: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_calls or []):
        function = raw.get("function") or {}
        arguments = function.get("arguments") or {}
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, ensure_ascii=False)
        calls.append(
            {
                "id": raw.get("id") or f"call_{uuid4().hex[:24]}",
                "index": index,
                "type": "function",
                "function": {
                    "name": function.get("name") or "",
                    "arguments": arguments,
                },
            }
        )
    return calls


def ollama_payload(body: dict[str, Any], *, stream: bool) -> dict[str, Any]:
    options: dict[str, Any] = {}
    option_map = {
        "temperature": "temperature",
        "top_p": "top_p",
        "max_tokens": "num_predict",
        "seed": "seed",
        "stop": "stop",
    }
    for source, target in option_map.items():
        if body.get(source) is not None:
            options[target] = body[source]
    if "num_predict" in options:
        options["num_predict"] = max(int(options["num_predict"]), 512)

    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "messages": body.get("messages") or [],
        "stream": stream,
        "think": THINK,
        "keep_alive": KEEP_ALIVE,
        "options": options,
    }
    if body.get("tools"):
        payload["tools"] = body["tools"]
    if body.get("response_format", {}).get("type") == "json_object":
        payload["format"] = "json"
    return payload


def completion_response(
    raw: dict[str, Any], request_id: str, created: int
) -> dict[str, Any]:
    message = raw.get("message") or {}
    tool_calls = openai_tool_calls(message.get("tool_calls"))
    result_message: dict[str, Any] = {
        "role": "assistant",
        "content": final_content(message.get("content") or ""),
    }
    if tool_calls:
        result_message["tool_calls"] = tool_calls
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": created,
        "model": OLLAMA_MODEL,
        "choices": [
            {
                "index": 0,
                "message": result_message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": raw.get("prompt_eval_count") or 0,
            "completion_tokens": raw.get("eval_count") or 0,
            "total_tokens": (raw.get("prompt_eval_count") or 0)
            + (raw.get("eval_count") or 0),
        },
    }


async def ollama_error(response: httpx.Response) -> HTTPException:
    detail = response.text[:1000]
    return HTTPException(status_code=response.status_code, detail=detail)


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            response.raise_for_status()
            models = response.json().get("models") or []
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}") from exc

    loaded = next(
        (model for model in models if model.get("name") == OLLAMA_MODEL), None
    )
    if not loaded:
        raise HTTPException(status_code=503, detail=f"{OLLAMA_MODEL} is not loaded")
    size = int(loaded.get("size") or 0)
    size_vram = int(loaded.get("size_vram") or 0)
    return {
        "status": "ok",
        "model": OLLAMA_MODEL,
        "gpu_resident": size > 0 and size_vram >= size,
    }


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": OLLAMA_MODEL,
                "object": "model",
                "created": 0,
                "owned_by": "ollama-local",
            }
        ],
    }


@app.post("/test/429/v1/chat/completions")
async def forced_rate_limit() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": {"message": "controlled failover test", "code": 429}},
    )


async def stream_completion(
    body: dict[str, Any], request_id: str, created: int
) -> AsyncIterator[str]:
    timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=10)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_BASE_URL}/api/chat",
            json=ollama_payload(body, stream=True),
        ) as response:
            if response.status_code >= 400:
                payload = {
                    "error": {
                        "message": (await response.aread()).decode(
                            "utf-8", errors="replace"
                        )[:1000],
                        "code": response.status_code,
                    }
                }
                yield f"data: {json.dumps(payload)}\n\n"
                yield "data: [DONE]\n\n"
                return

            sent_role = False
            content_buffer = ""
            reasoning_closed = THINK
            async for line in response.aiter_lines():
                if not line:
                    continue
                raw = json.loads(line)
                message = raw.get("message") or {}
                delta: dict[str, Any] = {}
                if not sent_role:
                    delta["role"] = "assistant"
                    sent_role = True
                if message.get("content"):
                    content = message["content"]
                    if reasoning_closed:
                        delta["content"] = content
                    else:
                        content_buffer += content
                        if "</think>" in content_buffer:
                            reasoning_closed = True
                            cleaned = final_content(content_buffer)
                            content_buffer = ""
                            if cleaned:
                                delta["content"] = cleaned
                tool_calls = openai_tool_calls(message.get("tool_calls"))
                if tool_calls:
                    delta["tool_calls"] = tool_calls
                finish_reason = None
                if raw.get("done"):
                    if content_buffer:
                        cleaned = final_content(content_buffer)
                        content_buffer = ""
                        if cleaned:
                            delta["content"] = cleaned
                    finish_reason = "tool_calls" if tool_calls else "stop"
                chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": OLLAMA_MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": finish_reason,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    request_id = f"chatcmpl-{uuid4().hex}"
    created = int(time.time())
    if body.get("stream"):
        return StreamingResponse(
            stream_completion(body, request_id, created),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=10)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=ollama_payload(body, stream=False),
        )
    if response.status_code >= 400:
        raise await ollama_error(response)
    return completion_response(response.json(), request_id, created)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
