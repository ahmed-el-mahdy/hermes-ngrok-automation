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


def configured_flag(name: str, default: bool = True) -> bool:
    value = configured_value(name)
    if not value:
        return default
    return value.lower() not in {"0", "false", "no", "off", "disabled"}


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
details: dict[str, dict] = {}
models: dict[str, str] = {}
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

    started = time.monotonic()
    local_final = client.post(
        f"{BRIDGE_URL}/v1/chat/completions",
        json={
            "model": "qwen3-4b-gpu:latest",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer only with the final answer. Never show reasoning."
                    ),
                },
                {
                    "role": "user",
                    "content": "/no_think\nرد بكلمة تمام فقط",
                },
            ],
            "temperature": 0,
            "max_tokens": 512,
        },
    )
    timings["local_no_reasoning"] = round(time.monotonic() - started, 2)
    local_final.raise_for_status()
    local_content = (
        local_final.json().get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    checks["local_no_reasoning"] = (
        local_content == "تمام" and "</think>" not in local_content
    )
    if not checks["local_no_reasoning"]:
        details["local_no_reasoning"] = {
            "content_excerpt": local_content[:400],
        }

    nara_key = configured_value("NARAROUTER_API_KEY")
    if nara_key and configured_flag("NARAROUTER_ENABLED"):
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
            if not nara.is_success:
                checks[check_name] = False
                details[check_name] = {
                    "status_code": nara.status_code,
                    "error_excerpt": nara.text[:400],
                }
                continue
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
        if not ollama_cloud.is_success:
            checks["ollama_cloud_tool_call"] = False
            details["ollama_cloud_tool_call"] = {
                "status_code": ollama_cloud.status_code,
                "error_excerpt": ollama_cloud.text[:400],
            }
        else:
            checks["ollama_cloud_tool_call"] = bool(
                ollama_cloud.json().get("choices", [{}])[0]
                .get("message", {})
                .get("tool_calls")
            )

    openrouter_key = configured_value("OPENROUTER_API_KEY")
    if openrouter_key:
        override = configured_value("OPENROUTER_TEST_MODEL")
        openrouter_routes = (
            [("openrouter_tool_call", override)]
            if override
            else [
                (
                    "openrouter_ling_tool_call",
                    "inclusionai/ling-3.0-flash:free",
                ),
                (
                    "openrouter_free_router_tool_call",
                    "openrouter/free",
                ),
            ]
        )
        for check_name, openrouter_model in openrouter_routes:
            models[check_name] = openrouter_model
            started = time.monotonic()
            openrouter = client.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {openrouter_key}"},
                json=tool_payload(openrouter_model),
            )
            timings[check_name] = round(time.monotonic() - started, 2)
            if not openrouter.is_success:
                checks[check_name] = False
                details[check_name] = {
                    "status_code": openrouter.status_code,
                    "error_excerpt": openrouter.text[:400],
                }
                continue
            openrouter_choice = openrouter.json().get("choices", [{}])[0]
            openrouter_message = openrouter_choice.get("message", {})
            checks[check_name] = bool(openrouter_message.get("tool_calls"))
            if not checks[check_name]:
                details[check_name] = {
                    "finish_reason": openrouter_choice.get("finish_reason"),
                    "content_excerpt": str(
                        openrouter_message.get("content") or ""
                    )[:400],
                }

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
            "models": models,
            "failure_details": details,
            "seconds": timings,
        },
        indent=2,
        sort_keys=True,
    )
)
raise SystemExit(0 if not failed else 1)
