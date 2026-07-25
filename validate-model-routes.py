#!/opt/hermes/.venv/bin/python
"""Validate the independent NaraRouter, local bridge, and gateway routes."""

from __future__ import annotations

import json
import os
import time

import httpx


NARA_URL = "https://router.bynara.id/v1/chat/completions"
OLLAMA_CLOUD_URL = "https://ollama.com/v1/chat/completions"
BRIDGE_URL = "http://ollama-bridge:8000"
GATEWAY_URL = "http://127.0.0.1:8642/v1/chat/completions"


def tool_payload(model: str) -> dict:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Use lookup_status with target hermes. Do not answer directly."
                ),
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup_status",
                    "description": "Read service status",
                    "parameters": {
                        "type": "object",
                        "properties": {"target": {"type": "string"}},
                        "required": ["target"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 160,
    }


checks: dict[str, bool] = {}
timings: dict[str, float] = {}
timeout = httpx.Timeout(90, connect=10)

with httpx.Client(timeout=timeout) as client:
    started = time.monotonic()
    health = client.get(f"{BRIDGE_URL}/health")
    timings["local_health"] = round(time.monotonic() - started, 2)
    health.raise_for_status()
    checks["local_gpu_resident"] = health.json().get("gpu_resident") is True

    started = time.monotonic()
    local = client.post(
        f"{BRIDGE_URL}/v1/chat/completions",
        json=tool_payload("qwen3-4b-gpu:latest"),
    )
    timings["local_tool_call"] = round(time.monotonic() - started, 2)
    local.raise_for_status()
    checks["local_tool_call"] = bool(
        local.json().get("choices", [{}])[0]
        .get("message", {})
        .get("tool_calls")
    )

    nara_key = os.getenv("NARAROUTER_API_KEY", "")
    if nara_key:
        started = time.monotonic()
        nara = client.post(
            NARA_URL,
            headers={"Authorization": f"Bearer {nara_key}"},
            json=tool_payload("mistral-large"),
        )
        timings["nara_tool_call"] = round(time.monotonic() - started, 2)
        nara.raise_for_status()
        checks["nara_tool_call"] = bool(
            nara.json().get("choices", [{}])[0]
            .get("message", {})
            .get("tool_calls")
        )

    ollama_key = os.getenv("OLLAMA_API_KEY", "")
    if ollama_key:
        started = time.monotonic()
        ollama_cloud = client.post(
            OLLAMA_CLOUD_URL,
            headers={"Authorization": f"Bearer {ollama_key}"},
            json=tool_payload("gpt-oss:20b"),
        )
        timings["ollama_cloud_tool_call"] = round(
            time.monotonic() - started, 2
        )
        ollama_cloud.raise_for_status()
        checks["ollama_cloud_tool_call"] = bool(
            ollama_cloud.json().get("choices", [{}])[0]
            .get("message", {})
            .get("tool_calls")
        )

    api_key = os.getenv("API_SERVER_KEY", "")
    if api_key:
        started = time.monotonic()
        gateway = client.post(
            GATEWAY_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "hermes-agent",
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with exactly ROUTE_OK and no other text.",
                    }
                ],
                "stream": False,
            },
        )
        timings["gateway_primary"] = round(time.monotonic() - started, 2)
        gateway.raise_for_status()
        content = (
            gateway.json().get("choices", [{}])[0].get("message", {}).get("content")
            or ""
        )
        checks["gateway_primary"] = "ROUTE_OK" in content

failed = sorted(name for name, passed in checks.items() if not passed)
print(
    json.dumps(
        {
            "passed": not failed,
            "passed_count": sum(checks.values()),
            "check_count": len(checks),
            "failed_checks": failed,
            "checks": checks,
            "seconds": timings,
        },
        indent=2,
        sort_keys=True,
    )
)
raise SystemExit(0 if not failed else 1)
