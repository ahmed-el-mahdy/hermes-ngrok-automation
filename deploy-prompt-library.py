import json
import os
import urllib.error
import urllib.request


BASE = "http://127.0.0.1:3000/api/v1"


def request(path, method="GET", payload=None, token=""):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
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
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {body[:500]}") from exc


_, signin = request(
    "/auths/signin",
    method="POST",
    payload={"email": os.environ["PORTAL_EMAIL"], "password": os.environ["PORTAL_PASSWORD"]},
)
token = (signin or {}).get("token")
if not token:
    raise SystemExit("Portal authentication failed")

prompts = [
    (
        "hermes-code-feature",
        "Code a feature",
        """Use CODER. Implement this feature: {{feature}}\n\nRead existing files first, keep the change focused, add tests proportional to risk, execute them, and report files changed plus exact verification results. Use File System Manager, Code Executor, Shell Command Runner, and Git Operations as needed. Do not claim success without tool output.""",
    ),
    (
        "hermes-research-topic",
        "Research a topic",
        """Use SEARCHER. Research: {{topic}}\n\nUse Web Research for current sources, cross-check material claims, distinguish facts from inference, and save a cited report under searcher/output. State source dates and unavailable information.""",
    ),
    (
        "hermes-build-project",
        "Build a project",
        """Use BUILDER. Build: {{project}}\n\nCreate the smallest complete reproducible project under builder/output, install only required dependencies, run checks or the application, and save setup instructions. Use File System Manager, Shell Command Runner, Code Executor, Git Operations, and Agent Evaluator.""",
    ),
    (
        "hermes-review-code",
        "Review existing code",
        """Use REVIEWER. Review this target: {{target}}\n\nPrioritize correctness, regressions, security, validation, and missing tests. Run safe checks where possible. Put findings first with file references and evidence, then save the review under reviewer/output. Do not modify code unless asked.""",
    ),
    (
        "hermes-orchestrate",
        "Multi-step ORCHESTRATOR task",
        """Use ORCHESTRATOR for this objective: {{objective}}\n\nBreak it into verified phases, execute with the canonical tools, persist artifacts in the Hermes workspace, and track evidence. Specialist names are workflow roles, not callable subagents. End with TASK, STEPS COMPLETED, RESULT, ISSUES, and NEXT.""",
    ),
    (
        "hermes-continue",
        "Continue previous task",
        """Use COORDINATOR. Recall the saved task board and context for: {{task}}\n\nVerify existing artifacts before changing state, continue the highest-priority unblocked item, and save the updated TODO / IN_PROGRESS / BLOCKED / DONE board. Never mark DONE without evidence.""",
    ),
    (
        "hermes-save-remember",
        "Save and remember",
        """Save this artifact or decision: {{content}}\n\nUse File System Manager for the full durable artifact and Persistent Memory only for a compact, user-approved summary. Return the exact saved location and recall the memory once to verify it.""",
    ),
    (
        "hermes-recommend",
        "Get a recommendation",
        """Use CONSULTANT. Recommend an option for: {{decision}}\n\nCompare alternatives with evidence, assumptions, cost, effort, reward, and risk. Use Web Research when facts may have changed, save the full recommendation under consultant/output, and state uncertainty clearly.""",
    ),
    (
        "hermes-scrape-data",
        "Scrape and structure data",
        """Use SCRAPER. Extract structured data from: {{url}}\n\nUse Web Research scrape_url_to_json, save the raw result under scraper/output, read it back, and transform only facts present in the retrieved page. Include the source URL and exact retrieval errors; never invent missing fields.""",
    ),
    (
        "hermes-debug",
        "Debug a problem",
        """Debug this problem: {{problem}}\n\nReproduce it, collect the smallest useful diagnostics, identify the root cause, implement a focused fix, and rerun the failing check. Use the relevant canonical tools and report command evidence plus remaining risk.""",
    ),
]

_, existing = request("/prompts/", token=token)
by_command = {item.get("command"): item for item in (existing or [])}
for command, name, content in prompts:
    payload = {
        "command": command,
        "name": name,
        "content": content,
        "data": {},
        "meta": {"description": "HERMES reusable workflow prompt"},
        "tags": ["hermes"],
        "access_grants": [],
        "commit_message": "Deploy canonical HERMES prompt library",
        "is_production": True,
    }
    current = by_command.get(command)
    if current:
        status, _ = request(
            f"/prompts/id/{current['id']}/update", method="POST", payload=payload, token=token
        )
        action = "updated"
    else:
        status, _ = request("/prompts/create", method="POST", payload=payload, token=token)
        action = "created"
    print(f"prompt={command}|status={status}|action={action}")

_, installed = request("/prompts/", token=token)
installed_commands = {item.get("command") for item in (installed or [])}
required = {item[0] for item in prompts}
missing = sorted(required - installed_commands)
print(f"summary={len(required) - len(missing)}/{len(required)}")
print("missing=" + ",".join(missing))
raise SystemExit(1 if missing else 0)
