#!/usr/bin/env python3
"""Validate the Open WebUI mobile payload compatibility patch."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys


sys.path.insert(0, "/app/backend")

source = Path("/app/backend/open_webui/main.py").read_text(encoding="utf-8")
checks = {
    "patch_mobile_message_normalizer": "HERMES_MOBILE_MESSAGE_NORMALIZER"
    in source,
    "patch_normalize_before_chat": "HERMES_NORMALIZE_MOBILE_BEFORE_CHAT"
    in source,
    "patch_failed_placeholder_done": "HERMES_COMPLETE_FAILED_CHAT_PLACEHOLDER"
    in source,
}

from open_webui.main import _normalize_hermes_mobile_chat_payload


mobile_payload = {
    "model": "hermes",
    "messages": [
        {"role": "assistant", "content": []},
        {
            "role": "user",
            "content": [{"type": "text", "text": "Hi"}],
        },
        {"role": "assistant", "content": [], "output": []},
    ],
}
normalized = _normalize_hermes_mobile_chat_payload(copy.deepcopy(mobile_payload))
checks["mobile_placeholder_removed"] = [
    message.get("role") for message in normalized["messages"]
] == ["assistant", "user"]
checks["structured_user_content_preserved"] = (
    normalized["messages"][-1]["content"][0]["text"] == "Hi"
)

completed_payload = {
    "messages": [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
}
completed = _normalize_hermes_mobile_chat_payload(
    copy.deepcopy(completed_payload)
)
checks["completed_assistant_preserved"] = (
    completed["messages"][-1]["content"] == "Hello"
)

try:
    _normalize_hermes_mobile_chat_payload(
        {"messages": [{"role": "assistant", "content": []}]}
    )
except ValueError:
    checks["missing_user_rejected"] = True
else:
    checks["missing_user_rejected"] = False

failed = [name for name, passed in checks.items() if not passed]
print(
    json.dumps(
        {
            "passed": not failed,
            "passed_count": sum(checks.values()),
            "check_count": len(checks),
            "failed_checks": failed,
            "checks": checks,
        },
        indent=2,
    )
)
raise SystemExit(1 if failed else 0)
