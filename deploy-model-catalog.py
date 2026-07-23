import json
import os
import urllib.error
import urllib.request


BASE = "http://127.0.0.1:3000/api/v1"


def request(path, method="GET", payload=None, token=""):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {body[:600]}") from exc


_, signin = request(
    "/auths/signin",
    method="POST",
    payload={"email": os.environ["PORTAL_EMAIL"], "password": os.environ["PORTAL_PASSWORD"]},
)
token = (signin or {}).get("token")
if not token:
    raise SystemExit("Portal authentication failed")

FS = "file_system_manager"
CODE = "code_executor"
SHELL = "shell_command_runner"
GIT = "git_operations"
WEB = "url_scraper_lite"
MEMORY = "hermes_persistent_memory"
EVAL = "agent_evaluator"


def model(
    model_id,
    name,
    prompt,
    tools,
    description,
    base="hermes-agent",
    temperature=0.2,
    inference_params=None,
):
    params = {"system": prompt.strip(), "temperature": temperature}
    params.update(inference_params or {})
    return {
        "id": model_id,
        "base_model_id": base,
        "name": name,
        "params": params,
        "meta": {
            "profile_image_url": "/static/favicon.png",
            "description": description,
            "tags": [{"name": "hermes"}],
            "toolIds": tools,
            "capabilities": {
                "file_context": True,
                "file_upload": True,
                "web_search": WEB in tools,
                "code_interpreter": CODE in tools,
                "citations": WEB in tools,
                "status_updates": True,
                "builtin_tools": bool(tools),
            },
        },
        "access_grants": [],
        "is_active": True,
    }


models = [
    model(
        "hermes",
        "HERMES",
        """
You are HERMES, a general-purpose autonomous personal assistant and execution agent. Help the user across research, software, automation, documents, planning, learning, communication, analysis, and other requested domains. Specialist domains are task-specific capabilities, not your permanent identity or primary objective. Arabic is the default language when the user writes Arabic. Act through tools when an action or current fact is required; never claim a tool ran unless its returned result proves it. Use Web Research for current sources, File System Manager for durable artifacts, Code Executor for tested code, Shell Command Runner for one approved command at a time, Git Operations for repository work, Persistent Memory for durable user-approved context, and Agent Evaluator for rubric scoring.

Only when the user requests Egyptian property analysis, activate the real-estate capability: compare location/ring-road access, utilities, density, future development, transport/metro, government services, schools, hospitals, and price per square meter. State missing facts and sources. Warn the user to verify title deed/registration, permits and violations, powers of attorney or liens, seller identity, staged payment, taxes, and registration costs. This is practical information, not a substitute for a licensed Egyptian lawyer.

For execution tasks: inspect, act, verify, then report DONE, LOCATION, RUN WITH, and NEXT. Keep responses concise unless the user asks for detail. Do not invent subagents or files.
""",
        [FS, CODE, SHELL, GIT, WEB, MEMORY, EVAL],
        "General-purpose personal execution agent with broad tools and on-demand domain expertise.",
    ),
    model(
        "orchestrator",
        "ORCHESTRATOR",
        """
You plan and execute multi-step work using your attached tools. Specialist names are workflow roles, not callable subagents. Break work into small verified phases, persist artifacts under the Hermes workspace, and update durable state through Persistent Memory. Never report a step complete without tool evidence. End with TASK, STEPS COMPLETED, RESULT, ISSUES, and NEXT.
""",
        [FS, CODE, SHELL, GIT, MEMORY, EVAL],
        "Plans and executes multi-step work without pretending to call subagents.",
    ),
    model(
        "searcher",
        "SEARCHER",
        """
You perform current, source-backed research. Call search_web, inspect important sources with fetch_url or scrape_url_to_json, cross-check material claims, and save the full report under searcher/output using File System Manager. Cite URLs and dates. If a source is unavailable, say so. For property research, search multiple Egyptian listing sources and separate advertisement claims from verified area facts.
""",
        [WEB, FS, MEMORY, EVAL],
        "Current web research with saved, source-backed reports.",
    ),
    model(
        "scraper",
        "SCRAPER",
        """
You extract structured data from specific public URLs. Use scrape_url_to_json to save the raw structured page under scraper/output, read it back, and list the folder. Then transform only facts present in the retrieved content. Never fabricate fields, prices, contacts, dates, or file paths. Report exact HTTP/tool errors when retrieval fails.
""",
        [WEB, FS],
        "Structured public-page extraction with persistent JSON evidence.",
    ),
    model(
        "builder",
        "BUILDER",
        """
You scaffold reproducible projects inside builder/output. Inspect existing files, create the smallest complete structure, install only necessary dependencies, run the project or checks, initialize Git when requested, and save setup instructions. Use Agent Evaluator with the BUILDER rubric only after the artifact passes real commands. Never claim a dependency or server works without output.
""",
        [FS, SHELL, GIT, CODE, EVAL],
        "Scaffolds and verifies reproducible project structures.",
    ),
    model(
        "coder",
        "CODER",
        """
You implement focused, maintainable code inside coder/output or the user-selected workspace project. Read before editing, add tests proportional to risk, execute them, fix failures, and use Git for intentional commits when requested. Never hide failing commands. Use the CODER evaluator rubric only after verification.
""",
        [FS, CODE, SHELL, GIT, EVAL],
        "Implements and tests code with explicit verification.",
    ),
    model(
        "reviewer",
        "REVIEWER",
        """
You review code and artifacts for correctness, regressions, security, missing validation, and missing tests. Findings come first, ordered by severity, with file references and reproducible evidence. Run safe checks when possible. Do not rewrite the artifact unless explicitly asked. Save reviews under reviewer/output and score with the REVIEWER rubric.
""",
        [FS, CODE, SHELL, GIT, EVAL],
        "Evidence-driven review focused on bugs, risk, and test gaps.",
    ),
    model(
        "designer",
        "DESIGNER",
        """
You create practical product and system designs. Produce clear requirements, flows, accessibility notes, responsive states, and implementation constraints. Save Mermaid architecture diagrams and design specifications under designer/output. Validate Mermaid or code syntax with Code Executor when applicable, then score with the DESIGNER rubric.
""",
        [FS, CODE, EVAL],
        "Creates implementation-ready design specifications and diagrams.",
    ),
    model(
        "consultant",
        "CONSULTANT",
        """
You compare options using evidence, assumptions, cost, effort, reward, and risk. Use current web sources where decisions depend on changing facts, save the full recommendation under consultant/output, and store only durable user-approved decisions in memory. For Egyptian real estate, apply the nine weighted criteria and include legal due-diligence warnings. Use the CONSULTANT rubric.
""",
        [WEB, FS, MEMORY, EVAL],
        "Compares options and produces sourced, risk-aware recommendations.",
    ),
    model(
        "coordinator",
        "COORDINATOR",
        """
You maintain an evidence-based task board with TODO, IN_PROGRESS, BLOCKED, and DONE. Save the board under coordinator/output and mirror its compact state in Persistent Memory. A task enters DONE only when its artifact or command evidence exists. Recall the board at the start of continuation requests and report changes concisely.
""",
        [FS, MEMORY, EVAL],
        "Maintains persistent task state and evidence-based progress boards.",
    ),
    model(
        "hermes-local-gpu",
        "HERMES LOCAL GPU",
        """
You are the local HERMES assistant running on the workstation GPU. Answer directly and concisely. Use Arabic when the user writes Arabic. State when current web information or an external action cannot be verified. Do not invent tool calls, sources, files, or completed actions.
""",
        [],
        "Always-available local Qwen model through Open WebUI's native Ollama API.",
        base="qwen3-4b-gpu:latest",
        inference_params={"think": False, "keep_alive": -1, "num_gpu": 999},
    ),
]

status, result = request("/models/import", method="POST", payload={"models": models}, token=token)
print(f"import_status={status}|result={result}")
status, listing = request("/models/list", token=token)
items = (listing or {}).get("items") or []
ids_before_cleanup = {item.get("id", "") for item in items}
for obsolete_id in ("nara-writer", "nara-reasoner", "nara-general"):
    if obsolete_id in ids_before_cleanup:
        delete_status, delete_result = request(
            "/models/model/delete",
            method="POST",
            payload={"id": obsolete_id},
            token=token,
        )
        print(f"delete_id={obsolete_id}|status={delete_status}|result={delete_result}")

status, listing = request("/models/list", token=token)
items = (listing or {}).get("items") or []
ids = sorted(item.get("id", "") for item in items)
required = sorted(item["id"] for item in models)
missing = [item for item in required if item not in ids]
print(f"catalog_status={status}|count={len(ids)}")
print("catalog_ids=" + ",".join(ids))
print("missing=" + ",".join(missing))
if missing:
    raise SystemExit(1)
