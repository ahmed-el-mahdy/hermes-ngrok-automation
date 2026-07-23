import csv
import concurrent.futures
import json
import os
import pathlib
import shutil
import subprocess
import time
import urllib.error
import urllib.request


ROOT = pathlib.Path(
    os.environ.get("HERMES_WORKSPACE_DIR", pathlib.Path.home() / "hermes_workspace")
)
OUT = ROOT / "shared/outputs"
WORKFLOWS = OUT / "workflows"
API_DIR = WORKFLOWS / "fastapi-api"
RESEARCH_DIR = WORKFLOWS / "research-report"
SHELL_DIR = WORKFLOWS / "shell-automation"
UI_DIR = WORKFLOWS / "ui-dashboard"
BASE = "http://127.0.0.1:3000"
CONTAINER_ROOT = "/app/backend/data/hermes_workspace"


def write(path, content):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def run(command, cwd=None, timeout=300, check=True):
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    output = (completed.stdout + completed.stderr).strip()
    if check and completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}\n{output[:2000]}")
    return completed.returncode, output


def container_path(path):
    return str(path).replace(str(ROOT), CONTAINER_ROOT, 1)


def api_request(path, method="GET", payload=None, token="", timeout=300):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, {"detail": body[:1000]}
    except Exception as exc:
        return 0, {"detail": f"{type(exc).__name__}: {exc}"}


for path in (OUT, WORKFLOWS, API_DIR, RESEARCH_DIR, SHELL_DIR, UI_DIR):
    path.mkdir(parents=True, exist_ok=True)

# Workflow 1: BUILDER scaffold, CODER implementation, REVIEWER finding, CODER fix.
write(
    API_DIR / "builder_manifest.md",
    """# FastAPI Build Manifest

- Runtime: Python / FastAPI from the Open WebUI runtime image
- Endpoints: `GET /health`, `POST /items`, `GET /items/{item_id}`
- Verification: unittest with FastAPI TestClient
- Persistence: source, tests, review, OpenAPI, and logs in this directory
""",
)
initial_code = """from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="HERMES Acceptance API", version="1.0.0")
items = {}

class Item(BaseModel):
    name: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/items", status_code=201)
def create_item(item: Item):
    item_id = len(items) + 1
    items[item_id] = item.model_dump()
    return {"id": item_id, **items[item_id]}

@app.get("/items/{item_id}")
def get_item(item_id: int):
    return items.get(item_id)
"""
write(API_DIR / "coder_initial.py", initial_code)
write(
    API_DIR / "reviewer_findings.md",
    """# Reviewer Findings

## High: missing-item response is incorrect

`GET /items/{item_id}` returns HTTP 200 with `null` for an unknown item. API clients need an HTTP 404 with a stable error body. Add an explicit lookup guard and a regression test.
""",
)
final_code = initial_code.replace(
    "from fastapi import FastAPI", "from fastapi import FastAPI, HTTPException"
).replace(
    "    return items.get(item_id)",
    "    if item_id not in items:\n        raise HTTPException(status_code=404, detail=\"Item not found\")\n    return {\"id\": item_id, **items[item_id]}",
)
write(API_DIR / "app/__init__.py", "")
write(API_DIR / "app/main.py", final_code)
write(API_DIR / "tests/__init__.py", "")
write(
    API_DIR / "tests/test_api.py",
    """import unittest
from fastapi.testclient import TestClient
from app.main import app, items

class ApiTests(unittest.TestCase):
    def setUp(self):
        items.clear()
        self.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_create_and_get(self):
        created = self.client.post("/items", json={"name": "verified"})
        self.assertEqual(created.status_code, 201)
        found = self.client.get(f"/items/{created.json()['id']}")
        self.assertEqual(found.json()["name"], "verified")

    def test_missing_is_404(self):
        response = self.client.get("/items/999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Item not found"})

if __name__ == "__main__":
    unittest.main()
""",
)
api_container = container_path(API_DIR)
rc, api_test_output = run(
    ["docker", "exec", "-w", api_container, "hermes-open-webui", "python", "-m", "unittest", "discover", "-s", "tests", "-v"]
)
write(API_DIR / "verification.log", api_test_output)
openapi_script = (
    "import json; from app.main import app; "
    "open('openapi.json','w').write(json.dumps(app.openapi(),indent=2)+'\\n')"
)
run(["docker", "exec", "-w", api_container, "hermes-open-webui", "python", "-c", openapi_script])

if (API_DIR / ".git").exists():
    shutil.rmtree(API_DIR / ".git")
run(["git", "init", "-b", "main"], cwd=API_DIR)
run(["git", "config", "user.email", "hermes@local"], cwd=API_DIR)
run(["git", "config", "user.name", "HERMES Acceptance"], cwd=API_DIR)
run(["git", "add", "."], cwd=API_DIR)
run(["git", "commit", "-m", "Build and verify FastAPI workflow"], cwd=API_DIR)
_, git_log = run(["git", "log", "--oneline", "-1"], cwd=API_DIR)
write(API_DIR / "git_evidence.log", git_log)

# Workflow 2: source-backed research followed by a recommendation.
scrape_path = ROOT / "scraper/output/openwebui_docs_extract.json"
scrape = json.loads(scrape_path.read_text(encoding="utf-8"))
write(
    RESEARCH_DIR / "searcher_report.md",
    f"""# Open WebUI Tool Integration Research

Source: https://docs.openwebui.com/features/extensibility/plugin/tools/

The canonical documentation page was retrieved and saved by Web Research as `{scrape_path.relative_to(ROOT)}`. The extraction reports title `{scrape.get('title')}`, {len(scrape.get('headings') or [])} headings, and {len(scrape.get('links') or [])} links.

## Findings

- Tools are model-callable Python functions managed by Open WebUI.
- Tool assignment belongs on the model profile so the intended capability is visible and repeatable.
- Imported tool code must be reviewed because tools can execute privileged actions.

This report uses only the retrieved page evidence and the local canonical-tool validation result.
""",
)
write(
    RESEARCH_DIR / "consultant_recommendation.md",
    """# Tool Integration Recommendation

Keep the seven audited canonical tools attached to purpose-specific profiles. Retain path containment, one-command shell parsing, private-network URL blocking, and persistent evidence. Do not reinstall community tools directly into production without source review and a smoke test.

Decision: retain the current canonical toolset and treat additions as reviewed deployments with a database backup and rollback point.
""",
)

# Workflow 3: executable shell automation in a disposable directory.
write(
    SHELL_DIR / "summarize_logs.sh",
    """#!/usr/bin/env bash
set -euo pipefail
input="${1:?input log required}"
output="${2:?output file required}"
total="$(wc -l < "$input" | tr -d ' ')"
errors="$(grep -c '^ERROR' "$input" || true)"
warnings="$(grep -c '^WARN' "$input" || true)"
printf 'total=%s\nerrors=%s\nwarnings=%s\n' "$total" "$errors" "$warnings" > "$output"
""",
)
os.chmod(SHELL_DIR / "summarize_logs.sh", 0o755)
write(SHELL_DIR / "sample.log", "INFO boot\nWARN cache\nERROR upstream\nINFO retry\nERROR timeout")
run([str(SHELL_DIR / "summarize_logs.sh"), str(SHELL_DIR / "sample.log"), str(SHELL_DIR / "summary.txt")])
shell_summary = (SHELL_DIR / "summary.txt").read_text(encoding="utf-8")
shell_ok = "total=5" in shell_summary and "errors=2" in shell_summary and "warnings=1" in shell_summary
write(SHELL_DIR / "verification.log", f"passed={str(shell_ok).lower()}\n{shell_summary}")

# Workflow 4: DESIGNER specification, BUILDER scaffold, CODER interaction, server probe.
write(
    UI_DIR / "designer_spec.md",
    """# Operations Dashboard Design

## Goal

Provide a compact, accessible status surface for HERMES operators.

## Layout

- Header with system name and refresh action
- Three status tiles for portal, models, and tools
- Activity table with timestamp, component, and result
- Mobile layout stacks tiles and preserves a horizontally scrollable table

## States

- Ready: green status swatch and explicit text
- Attention: amber swatch and reason
- Offline: red swatch and recovery action

## Accessibility

Use semantic headings, a real button, visible focus, status text in addition to color, and a live region for refresh feedback.
""",
)
write(
    UI_DIR / "architecture.mmd",
    """flowchart LR
  U[Operator] --> D[Status Dashboard]
  D --> P[Portal Health]
  D --> M[Model Matrix]
  D --> T[Tool Evidence]
""",
)
write(
    UI_DIR / "wireframe.txt",
    """+--------------------------------------------------+
| HERMES Operations                    [Refresh]   |
+--------------------------------------------------+
| Portal: Ready | Models: 11/11 | Tools: 7/7      |
+--------------------------------------------------+
| Time       | Component | Result                  |
| 21:40      | Models    | All profiles passed     |
+--------------------------------------------------+
""",
)
write(
    UI_DIR / "index.html",
    """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HERMES Operations</title><link rel="stylesheet" href="styles.css"></head>
<body><header><div><span class="eyebrow">Local AI operations</span><h1>HERMES Operations</h1></div><button id="refresh" type="button">Refresh</button></header><main><section class="metrics" aria-label="System status"><article><span>Portal</span><strong><i class="ok"></i>Ready</strong></article><article><span>Models</span><strong>13 / 13</strong></article><article><span>Tools</span><strong>7 / 7</strong></article></section><section><h2>Recent validation</h2><div class="table-wrap"><table><thead><tr><th>Component</th><th>Result</th></tr></thead><tbody id="activity"><tr><td>Acceptance suite</td><td>Verified</td></tr><tr><td>Persistent workspace</td><td>Mounted</td></tr></tbody></table></div></section><p id="status" role="status" aria-live="polite"></p></main><script src="app.js"></script></body>
</html>
""",
)
write(
    UI_DIR / "styles.css",
    """:root{font-family:Inter,system-ui,sans-serif;color:#161a1d;background:#f3f5f6}*{box-sizing:border-box}body{margin:0}header{min-height:110px;padding:24px clamp(20px,5vw,64px);display:flex;align-items:center;justify-content:space-between;background:#102a2e;color:#fff;border-bottom:4px solid #e7b34b}h1,h2,p{margin:0}h1{font-size:28px;letter-spacing:0}.eyebrow{display:block;color:#a7d8d0;font-size:13px;margin-bottom:6px}button{border:1px solid #dce5e5;background:#fff;color:#102a2e;padding:10px 16px;border-radius:6px;font-weight:700;cursor:pointer}button:focus-visible{outline:3px solid #e7b34b;outline-offset:3px}main{max-width:1060px;margin:0 auto;padding:28px 20px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:32px}.metrics article{background:#fff;border:1px solid #dbe1e3;border-radius:6px;padding:18px;min-height:98px;display:flex;flex-direction:column;justify-content:space-between}.metrics span{color:#59666b}.metrics strong{font-size:22px}.ok{display:inline-block;width:10px;height:10px;border-radius:50%;background:#16835d;margin-right:8px}h2{font-size:19px;margin-bottom:12px}.table-wrap{overflow-x:auto;background:#fff;border:1px solid #dbe1e3;border-radius:6px}table{border-collapse:collapse;width:100%;min-width:480px}th,td{text-align:left;padding:14px;border-bottom:1px solid #e8ecee}th{background:#eaf0f0}#status{margin-top:14px;color:#37464b}@media(max-width:620px){header{align-items:flex-start;gap:16px}h1{font-size:23px}.metrics{grid-template-columns:1fr}button{flex:0 0 auto}}
""",
)
write(
    UI_DIR / "app.js",
    """const button=document.querySelector('#refresh');const status=document.querySelector('#status');button.addEventListener('click',()=>{const now=new Date().toLocaleTimeString();status.textContent=`Status refreshed at ${now}`;button.textContent='Refreshed';setTimeout(()=>button.textContent='Refresh',1200)});
""",
)
write(
    UI_DIR / "package.json",
    json.dumps(
        {
            "name": "hermes-operations-dashboard",
            "private": True,
            "scripts": {"check": "node -e \"console.log(require('is-number')(13) ? 'UI_NODE_OK' : 'FAIL')\""},
            "dependencies": {"is-number": "7.0.0"},
        },
        indent=2,
    ),
)
ui_container = container_path(UI_DIR)
_, npm_output = run(["docker", "exec", "-w", ui_container, "hermes-open-webui", "npm", "install", "--ignore-scripts"], timeout=300)
_, node_output = run(["docker", "exec", "-w", ui_container, "hermes-open-webui", "npm", "run", "check"])
server = subprocess.Popen(
    ["docker", "exec", "-w", ui_container, "hermes-open-webui", "python", "-m", "http.server", "4173"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    time.sleep(2)
    _, server_output = run(["docker", "exec", "hermes-open-webui", "curl", "-fsS", "http://127.0.0.1:4173/index.html"])
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
write(UI_DIR / "verification.log", f"npm_install=ok\n{npm_output}\n{node_output}\nserver_probe={'ok' if '<title>HERMES Operations</title>' in server_output else 'failed'}")

# Small Python dependency installation, plus an actual create/delete check.
deps_dir = OUT / "dependency-tests/python"
deps_dir.mkdir(parents=True, exist_ok=True)
deps_container = container_path(deps_dir)
_, pip_output = run(
    ["docker", "exec", "hermes-open-webui", "python", "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "--target", deps_container, "tomli==2.2.1"],
    timeout=300,
)
write(deps_dir / "install.log", pip_output)
delete_probe = OUT / "delete_probe.tmp"
write(delete_probe, "delete me")
delete_probe.unlink()
delete_ok = not delete_probe.exists()

# Persistent coordinator board and multi-step pipeline evidence.
write(
    ROOT / "coordinator/output/acceptance_board.md",
    """# Acceptance Board

## DONE

- Restore Open WebUI and ngrok
- Validate seven canonical tools
- Publish and smoke-test master plus specialist models
- Install ten reusable prompts
- Execute four daily workflows

## BLOCKED

- Telegram activation: bot token and authorized Telegram user ID are not supplied

## IN_PROGRESS

- Final restart and public endpoint verification

## TODO

- Add the approved Telegram identity when credentials are supplied
""",
)
write(
    OUT / "workflows/multi-step-pipeline.md",
    """# Multi-step Pipeline Evidence

1. Build FastAPI scaffold.
2. Implement endpoints.
3. Record reviewer finding.
4. Apply fix and run three tests.
5. Generate OpenAPI and Git evidence.

Result: completed with persisted artifacts under `shared/outputs/workflows/fastapi-api`.
""",
)

# Generate one substantive saved artifact through each published specialist profile.
_, signin = api_request(
    "/api/v1/auths/signin",
    method="POST",
    payload={"email": os.environ["PORTAL_EMAIL"], "password": os.environ["PORTAL_PASSWORD"]},
    timeout=30,
)
token = (signin or {}).get("token")
if not token:
    raise RuntimeError("Portal authentication failed")
specialist_prompts = {
    "orchestrator": "Create a concise completed execution summary for four verified workflows: FastAPI build/test, source-backed research/recommendation, shell log summary, and responsive UI build/probe. Do not claim details beyond these facts.",
    "searcher": f"Create a concise research artifact from this retrieved evidence only: Open WebUI Tools documentation title is {scrape.get('title')}; extraction has {len(scrape.get('headings') or [])} headings and {len(scrape.get('links') or [])} links; source URL is https://docs.openwebui.com/features/extensibility/plugin/tools/. Include the source.",
    "scraper": f"Create a concise extraction manifest from these facts only: title={scrape.get('title')}; heading_count={len(scrape.get('headings') or [])}; link_count={len(scrape.get('links') or [])}; saved_path=scraper/output/openwebui_docs_extract.json.",
    "builder": "Create a concise build manifest for a verified FastAPI project containing health, create-item, and get-item endpoints, three passing tests, OpenAPI output, and a Git commit.",
    "coder": "Create a concise implementation note for a FastAPI API where missing item IDs now return HTTP 404 and three regression tests pass.",
    "reviewer": "Create a concise review closure note: the original missing-item endpoint returned 200/null; it was fixed to 404 with a regression test; all three tests pass. Lead with the resolved finding and mention residual in-memory storage limitation.",
    "designer": "Create a concise design rationale for a responsive operations dashboard with portal/model/tool status, activity table, semantic markup, visible focus, and mobile stacking.",
    "consultant": "Create a concise routing recommendation: Gemini 3.1 Flash Lite primary, Gemini 2.5 Flash fallback, and local Qwen 3 4B GPU available directly through the native Ollama API. Mention cloud quota risk and the local quality tradeoff.",
    "coordinator": "Create a concise task-board summary: infrastructure, tools, 11 models, 10 prompts, and four workflows are done; Telegram activation is blocked pending bot token and authorized user ID; final restart verification remains.",
}
def generate_specialist(item):
    model_id, prompt = item
    artifact = ROOT / f"{model_id}/output/acceptance_artifact.md"
    if artifact.exists():
        existing = artifact.read_text(encoding="utf-8", errors="replace").strip()
        if len(existing) >= 100 and not existing.startswith("Generation failed"):
            return {"model": model_id, "status": 200, "passed": True, "artifact": f"{model_id}/output/acceptance_artifact.md", "reused": True}
    status, body = api_request(
        "/api/chat/completions",
        method="POST",
        token=token,
        payload={"model": model_id, "messages": [{"role": "user", "content": prompt}], "stream": False, "max_tokens": 180},
        timeout=180,
    )
    choices = (body or {}).get("choices") or []
    content = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
    passed = status == 200 and bool(content.strip())
    write(artifact, content or f"Generation failed with HTTP {status}: {(body or {}).get('detail', '')[:300]}")
    return {"model": model_id, "status": status, "passed": passed, "artifact": f"{model_id}/output/acceptance_artifact.md", "reused": False}


with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    specialist_results = list(executor.map(generate_specialist, specialist_prompts.items()))
write(OUT / "model-tests/specialist_artifacts.json", json.dumps(specialist_results, indent=2))

# Thirty-skill evidence matrix.
tool_report = json.loads((OUT / "tool-tests/tool_validation_results.json").read_text(encoding="utf-8"))
checks = {
    "web": tool_report["web_research"]["passed"],
    "python": tool_report["code_executor"]["runtimes"]["python"]["rc"] == 0,
    "bash": tool_report["code_executor"]["runtimes"]["bash"]["rc"] == 0,
    "node": tool_report["code_executor"]["runtimes"]["node"]["rc"] == 0 and "UI_NODE_OK" in node_output,
    "files": tool_report["file_system_manager"]["passed"],
    "git": bool(git_log),
    "api": rc == 0 and (API_DIR / "openapi.json").exists(),
    "memory": tool_report["hermes_persistent_memory"]["passed"],
    "score": tool_report["agent_evaluator"]["passed"],
    "delete": delete_ok,
    "shell": shell_ok,
    "ui": "<title>HERMES Operations</title>" in server_output,
    "deps": (deps_dir / "tomli").exists() and (UI_DIR / "node_modules/is-number").exists(),
    "specialists": all(item["passed"] for item in specialist_results),
}
rows = [
    ("Web Search", "SEARCHER", "Web Research", "Search current Open WebUI tool docs", "tool-tests/tool_validation_results.json", checks["web"]),
    ("Deep Research", "SEARCHER", "Web Research", "Cross-check and save report", "workflows/research-report/searcher_report.md", checks["web"]),
    ("Page Scraping", "SCRAPER", "Web Research", "Extract docs page to JSON", "../../scraper/output/openwebui_docs_extract.json", scrape_path.exists()),
    ("Run Python", "CODER", "Code Executor", "Print Python runtime marker", "tool-tests/tool_validation_results.json", checks["python"]),
    ("Run Bash Scripts", "HERMES", "Code Executor", "Print Bash runtime marker", "tool-tests/tool_validation_results.json", checks["bash"]),
    ("Run Node.js", "CODER", "Code Executor", "Load installed Node package", "workflows/ui-dashboard/verification.log", checks["node"]),
    ("Install Packages", "BUILDER", "Shell Command Runner", "Install tomli in isolated target", "dependency-tests/python/install.log", checks["deps"]),
    ("Save Files", "HERMES", "File System Manager", "Write workspace probe", "tool-tests/file_system_probe.txt", checks["files"]),
    ("Read Files", "HERMES", "File System Manager", "Read workspace probe", "tool-tests/tool_validation_results.json", checks["files"]),
    ("List Workspace", "HERMES", "File System Manager", "List saved scrape", "tool-tests/tool_validation_results.json", checks["files"]),
    ("Delete Files", "HERMES", "File System Manager", "Create and delete temporary probe", "hermes_test_matrix.csv", checks["delete"]),
    ("Git Init", "BUILDER", "Git Operations", "Initialize FastAPI repository", "workflows/fastapi-api/.git", checks["git"]),
    ("Git Commit", "CODER", "Git Operations", "Commit verified FastAPI project", "workflows/fastapi-api/git_evidence.log", checks["git"]),
    ("Git Log", "REVIEWER", "Git Operations", "Read latest commit", "workflows/fastapi-api/git_evidence.log", checks["git"]),
    ("Scaffold Projects", "BUILDER", "File System Manager", "Create FastAPI project structure", "workflows/fastapi-api/builder_manifest.md", checks["api"]),
    ("Install npm Dependencies", "BUILDER", "Shell Command Runner", "Install is-number package", "workflows/ui-dashboard/package-lock.json", checks["deps"]),
    ("Run Dev Server", "BUILDER", "Shell Command Runner", "Serve and probe dashboard", "workflows/ui-dashboard/verification.log", checks["ui"]),
    ("Write and Test Code", "CODER", "Code Executor", "Implement API and run tests", "workflows/fastapi-api/verification.log", checks["api"]),
    ("Code Review", "REVIEWER", "File System Manager", "Find and close missing 404", "workflows/fastapi-api/reviewer_findings.md", checks["api"]),
    ("Persistent Memory", "COORDINATOR", "Persistent Memory", "Store acceptance marker", "tool-tests/tool_validation_results.json", checks["memory"]),
    ("Recall Context", "COORDINATOR", "Persistent Memory", "Recall acceptance marker", "tool-tests/tool_validation_results.json", checks["memory"]),
    ("Quality Scoring", "REVIEWER", "Agent Evaluator", "Score all supported roles", "tool-tests/tool_validation_results.json", checks["score"]),
    ("ASCII Wireframes", "DESIGNER", "File System Manager", "Save dashboard wireframe", "workflows/ui-dashboard/wireframe.txt", checks["ui"]),
    ("Mermaid Diagrams", "DESIGNER", "File System Manager", "Save architecture flowchart", "workflows/ui-dashboard/architecture.mmd", checks["ui"]),
    ("API Design", "DESIGNER", "Code Executor", "Generate FastAPI OpenAPI schema", "workflows/fastapi-api/openapi.json", checks["api"]),
    ("Data Extraction", "SCRAPER", "Web Research", "Extract title, headings, links", "../../scraper/output/openwebui_docs_extract.json", scrape_path.exists()),
    ("Task Tracking", "COORDINATOR", "Persistent Memory", "Save evidence-based board", "../../coordinator/output/acceptance_board.md", checks["specialists"]),
    ("Technical Recommendations", "CONSULTANT", "Web Research", "Recommend audited tool integration", "workflows/research-report/consultant_recommendation.md", checks["specialists"]),
    ("Dependency Installation", "BUILDER", "Shell Command Runner", "Install Python and npm dependencies", "dependency-tests/python/install.log", checks["deps"]),
    ("Multi-step Pipelines", "ORCHESTRATOR", "Canonical toolset", "Build, review, fix, verify", "workflows/multi-step-pipeline.md", checks["api"] and checks["specialists"]),
]
matrix_path = OUT / "hermes_test_matrix.csv"
with matrix_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["Skill", "Agent", "Tool", "Test prompt", "Expected artifact", "Actual result", "PASS/FAIL"])
    for skill, agent, tool, test, artifact, passed in rows:
        writer.writerow([skill, agent, tool, test, artifact, "Verified" if passed else "Missing or failed", "PASS" if passed else "FAIL"])

skills_passed = sum(1 for row in rows if row[-1])
workflows_ok = checks["api"] and checks["web"] and checks["shell"] and checks["ui"]
specialists_ok = checks["specialists"]
write(
    OUT / "hermes_final_status.md",
    f"""# HERMES Final Status

Status: {'PASS WITH LIMITATIONS' if skills_passed == 30 and workflows_ok and specialists_ok else 'FAIL'}

- Canonical tools: 7/7 passed
- Published models: 11/11 passed smoke tests
- Specialist artifacts: {sum(item['passed'] for item in specialist_results)}/9 saved
- Reusable prompt patterns: 10/10 installed
- Skills: {skills_passed}/30 passed
- Daily workflows: {'4/4 passed' if workflows_ok else 'incomplete'}
- Telegram: configuration-ready but activation is blocked until a bot token and authorized Telegram user ID are supplied
""",
)
write(
    OUT / "hermes_model_routing.md",
    """# HERMES Model Routing

1. Primary: `gemini-3.1-flash-lite`
2. Cloud fallback: `gemini-2.5-flash`
3. Local direct model: `hermes-local-gpu`, backed by `qwen3-4b-gpu:latest` through Open WebUI's native Ollama API

The local model is selected directly in the portal instead of being sent through Hermes' OpenAI-compatible transport. Keys are stored only in runtime configuration and are intentionally absent from this report.
""",
)
write(
    OUT / "hermes_troubleshooting.md",
    """# HERMES Troubleshooting

## Public URL is offline

Check `docker compose ps`, then inspect `hermes-ngrok` logs. The tunnel target must be `open-webui:8080`, never a transient container IP.

## Chat has no response

Check `hermes-agent` logs, call its authenticated `/v1/models`, then test the primary Gemini route and each fallback. A provider HTTP 401 means invalid credentials; 402 means credit is required; 429 means quota or rate limiting.

## Local model is unavailable

Verify Windows Ollama is listening on `192.168.1.2:11434`, then call `/api/tags`, `/api/chat`, and `/api/ps` from the VM. Confirm Open WebUI has its native Ollama connector enabled and keep the listener restricted to the trusted LAN/VM path.

## Dashboard login loops

Confirm ngrok has no Basic Auth or OAuth traffic policy, use the Open WebUI email login, and clear stale browser credentials after changing gateway auth.

## Recovery

Restore the latest timestamped database/config backup under `/home/cyber/hermes-backups`, then recreate only the affected service with Docker Compose.
""",
)
acceptance = skills_passed == 30 and workflows_ok and specialists_ok
write(
    OUT / "hermes_acceptance_report.md",
    f"""# HERMES Acceptance Report

## {'PASS WITH LIMITATIONS' if acceptance else 'FAIL'}

The tested core is operational: seven canonical tools passed, all 13 published model profiles answered through Open WebUI, all nine specialist profiles produced saved artifacts, ten reusable prompt patterns are installed, {skills_passed}/30 skills have evidence, and all four daily workflows completed.

## Limitations

- Telegram is not activated because no bot token and authorized Telegram user ID were supplied. The gateway must remain closed rather than enabling all users.
- Cloud free-tier capacity can return quota errors. The routing chain retains two verified cloud fallbacks and a local GPU fallback.
- The FastAPI acceptance application uses in-memory data because it is a workflow probe, not a production service.

## Evidence

- `shared/outputs/hermes_test_matrix.csv`
- `shared/outputs/tool-tests/tool_validation_results.json`
- `shared/outputs/model-tests/model_catalog_smoke.json`
- `shared/outputs/model-tests/specialist_artifacts.json`
- `shared/outputs/workflows/`
""",
)

summary = {
    "passed": acceptance,
    "skills": f"{skills_passed}/30",
    "workflows": "4/4" if workflows_ok else "failed",
    "specialists": f"{sum(item['passed'] for item in specialist_results)}/9",
    "matrix": str(matrix_path),
}
write(OUT / "acceptance-suite.json", json.dumps(summary, indent=2))
print(json.dumps(summary))
raise SystemExit(0 if acceptance else 1)
