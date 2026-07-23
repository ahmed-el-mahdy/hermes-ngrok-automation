import json
import os
import urllib.error
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:3000/api/v1"
EMAIL = os.environ["PORTAL_EMAIL"]
PASSWORD = os.environ["PORTAL_PASSWORD"]
SOURCE_DIR = Path(os.environ.get("TOOL_SOURCE_DIR", Path(__file__).resolve().parent / "openwebui-tools"))


def request(path, method="GET", payload=None, token=""):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {body[:500]}") from exc


status, signin = request(
    "/auths/signin",
    method="POST",
    payload={"email": EMAIL, "password": PASSWORD},
)
token = (signin or {}).get("token")
if status != 200 or not token:
    raise SystemExit("Portal authentication failed")

updates = {
    "file_system_manager": ("File System Manager", "Safely read, write, list, and delete files inside the Hermes workspace.", SOURCE_DIR / "file_system_manager.py"),
    "shell_command_runner": ("Shell Command Runner", "Run approved commands in the Hermes workspace without shell expansion.", SOURCE_DIR / "shell_command_runner.py"),
    "git_operations": ("Git Operations", "Run Git subcommands inside repositories under the Hermes workspace.", SOURCE_DIR / "git_operations.py"),
    "url_scraper_lite": ("Web Research", "Search the public web, fetch URLs, and save structured evidence.", SOURCE_DIR / "web_research.py"),
    "code_executor": ("Code Executor", "Execute Python, Bash, or Node.js with bounded runtime and output.", SOURCE_DIR / "code_executor.py"),
    "hermes_persistent_memory": ("Hermes Persistent Memory", "Store and recall durable key-value memory in the mounted Hermes workspace.", SOURCE_DIR / "hermes_persistent_memory.py"),
    "agent_evaluator": ("Agent Evaluator", "Validate and score specialist outputs against fixed quality rubrics.", SOURCE_DIR / "agent_evaluator.py"),
}

status, tools = request("/tools/", token=token)
existing_ids = {item.get("id", "") for item in (tools or [])}
for tool_id, (name, description, path) in updates.items():
    content = Path(path).read_text(encoding="utf-8")
    endpoint = f"/tools/id/{tool_id}/update" if tool_id in existing_ids else "/tools/create"
    status, response = request(
        endpoint,
        method="POST",
        payload={
            "id": tool_id,
            "name": name,
            "content": content,
            "meta": {"description": description},
            "access_grants": [],
        },
        token=token,
    )
    specs = (response or {}).get("specs") or []
    action = "updated" if tool_id in existing_ids else "created"
    print(f"{action}={tool_id}|status={status}|functions={','.join(item.get('name', '') for item in specs)}")

status, tools = request("/tools/", token=token)
existing_ids = {item.get("id", "") for item in (tools or [])}
for tool_id in ("brave_web_search", "web_search_lite"):
    if tool_id in existing_ids:
        status, response = request(f"/tools/id/{tool_id}/delete", method="DELETE", token=token)
        print(f"deleted={tool_id}|status={status}|result={response}")

status, tools = request("/tools/", token=token)
ids = sorted(item.get("id", "") for item in (tools or []))
print(f"canonical_tool_count={len(ids)}")
print("canonical_tool_ids=" + ",".join(ids))
if set(ids) != set(updates):
    raise SystemExit("Canonical tool set does not match the expected seven IDs")
