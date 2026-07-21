import json
import os
import pathlib
import urllib.error
import urllib.request


LOCAL = "http://127.0.0.1:3000"
WORKSPACE = pathlib.Path(
    os.environ.get("HERMES_WORKSPACE_DIR", pathlib.Path.home() / "hermes_workspace")
)
OUTPUT = WORKSPACE / "shared/outputs/deployment/recreation_validation.json"


def request(base, path, method="GET", payload=None, token="", timeout=180, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json", **(headers or {})}
    if token:
        merged["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=merged, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else None
            except json.JSONDecodeError:
                parsed = body
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        return exc.code, {"detail": exc.read().decode("utf-8", errors="replace")[:500]}
    except Exception as exc:
        return 0, {"detail": f"{type(exc).__name__}: {exc}"}


_, signin = request(
    LOCAL,
    "/api/v1/auths/signin",
    method="POST",
    payload={"email": os.environ["PORTAL_EMAIL"], "password": os.environ["PORTAL_PASSWORD"]},
    timeout=30,
)
token = (signin or {}).get("token")
if not token:
    raise SystemExit("Portal authentication failed after recreation")

models_status, models_body = request(LOCAL, "/api/v1/models/list", token=token)
models = (models_body or {}).get("items") or []
model_ids = {item.get("id") for item in models}
required_models = {
    "hermes", "orchestrator", "searcher", "scraper", "builder", "coder", "reviewer",
    "designer", "consultant", "coordinator", "nara-writer", "nara-reasoner", "nara-general",
}
tools_status, tools_body = request(LOCAL, "/api/v1/tools/", token=token)
tool_ids = {item.get("id") for item in (tools_body or [])}
required_tools = {
    "file_system_manager", "code_executor", "shell_command_runner", "git_operations",
    "url_scraper_lite", "hermes_persistent_memory", "agent_evaluator",
}
prompts_status, prompts_body = request(LOCAL, "/api/v1/prompts/", token=token)
prompt_commands = {item.get("command") for item in (prompts_body or [])}
required_prompts = {
    "hermes-code-feature", "hermes-research-topic", "hermes-build-project",
    "hermes-review-code", "hermes-orchestrate", "hermes-continue",
    "hermes-save-remember", "hermes-recommend", "hermes-scrape-data", "hermes-debug",
}
chat_status, chat_body = request(
    LOCAL,
    "/api/chat/completions",
    method="POST",
    token=token,
    payload={
        "model": "hermes",
        "messages": [{"role": "user", "content": "Reply exactly RECREATION_OK"}],
        "stream": False,
        "max_tokens": 60,
    },
)
choices = (chat_body or {}).get("choices") or []
chat_content = str((choices[0].get("message") or {}).get("content") or "") if choices else ""

public_url = os.environ["PUBLIC_URL"].rstrip("/")
public_status, _ = request(
    public_url,
    "/",
    timeout=45,
    headers={"ngrok-skip-browser-warning": "true"},
)
public_signin_status, public_signin = request(
    public_url,
    "/api/v1/auths/signin",
    method="POST",
    payload={"email": os.environ["PORTAL_EMAIL"], "password": os.environ["PORTAL_PASSWORD"]},
    timeout=45,
    headers={"ngrok-skip-browser-warning": "true"},
)

evidence_paths = [
    WORKSPACE / "shared/outputs/hermes_acceptance_report.md",
    WORKSPACE / "shared/outputs/hermes_test_matrix.csv",
    WORKSPACE / "shared/outputs/tool-tests/tool_validation_results.json",
    WORKSPACE / "shared/outputs/model-tests/model_catalog_smoke.json",
]
checks = {
    "local_signin": True,
    "models": models_status == 200 and required_models <= model_ids,
    "tools": tools_status == 200 and tool_ids == required_tools,
    "prompts": prompts_status == 200 and required_prompts <= prompt_commands,
    "chat": chat_status == 200 and "RECREATION_OK" in chat_content,
    "public_portal": public_status == 200,
    "public_signin": public_signin_status == 200 and bool((public_signin or {}).get("token")),
    "workspace_evidence": all(path.exists() and path.stat().st_size > 0 for path in evidence_paths),
}
report = {
    "passed": all(checks.values()),
    "public_url": public_url,
    "checks": checks,
    "counts": {"models": len(model_ids), "tools": len(tool_ids), "prompts": len(required_prompts & prompt_commands)},
    "chat_excerpt": " ".join(chat_content.split())[:120],
    "missing_models": sorted(required_models - model_ids),
    "missing_tools": sorted(required_tools - tool_ids),
    "missing_prompts": sorted(required_prompts - prompt_commands),
}
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report))
raise SystemExit(0 if report["passed"] else 1)
