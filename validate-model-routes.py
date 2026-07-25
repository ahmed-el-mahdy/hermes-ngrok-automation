#!/opt/hermes/.venv/bin/python
"""Validate every preferred cloud source, local bridge, and gateway route."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

import httpx


NARA_URL = "https://router.bynara.id/v1/chat/completions"
OLLAMA_CLOUD_URL = "https://ollama.com/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
BRIDGE_URL = "http://ollama-bridge:8000"
GATEWAY_URL = "http://127.0.0.1:8642/v1/chat/completions"
ENV_PATH = Path("/opt/data/.env")


def configured_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                candidate, value = line.split("=", 1)
                if candidate.strip() == name:
                    return value.strip()
    return ""


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
        "max_tokens": 320,
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

    nara_key = configured_value("NARAROUTER_API_KEY")
    if nara_key:
        for check_name, model in (
            ("nara_mistral_tool_call", "mistral-large"),
            ("nara_laguna_tool_call", "laguna-s-2.1"),
        ):
            started = time.monotonic()
            nara = client.post(
                NARA_URL,
                headers={"Authorization": f"Bearer {nara_key}"},
                json=tool_payload(model),
            )
            timings[check_name] = round(time.monotonic() - started, 2)
            nara.raise_for_status()
            checks[check_name] = bool(
                nara.json().get("choices", [{}])[0]
                .get("message", {})
                .get("tool_calls")
            )

    ollama_key = configured_value("OLLAMA_API_KEY")
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

    openrouter_key = configured_value("OPENROUTER_API_KEY")
    if openrouter_key:
        started = time.monotonic()
        openrouter = client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {openrouter_key}"},
            json=tool_payload(
                "nvidia/nemotron-3-super-120b-a12b:free"
            ),
        )
        timings["openrouter_tool_call"] = round(
            time.monotonic() - started, 2
        )
        openrouter.raise_for_status()
        checks["openrouter_tool_call"] = bool(
            openrouter.json().get("choices", [{}])[0]
            .get("message", {})
            .get("tool_calls")
        )

    api_key = configured_value("API_SERVER_KEY")
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
