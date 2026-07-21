import json
import os
import pathlib
import time
import urllib.error
import urllib.request


BASE = "http://127.0.0.1:3000"
WORKSPACE = pathlib.Path(
    os.environ.get("HERMES_WORKSPACE_DIR", pathlib.Path.home() / "hermes_workspace")
)
OUTPUT = WORKSPACE / "shared/outputs/model-tests/model_catalog_smoke.json"


def request(path, method="GET", payload=None, token="", timeout=300):
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
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"detail": body[:500]}
        return exc.code, parsed
    except Exception as exc:
        return 0, {"detail": f"{type(exc).__name__}: {exc}"}


_, signin = request(
    "/api/v1/auths/signin",
    method="POST",
    payload={"email": os.environ["PORTAL_EMAIL"], "password": os.environ["PORTAL_PASSWORD"]},
    timeout=30,
)
token = (signin or {}).get("token")
if not token:
    raise SystemExit("Portal authentication failed")

prompts = {
    "hermes": "Reply exactly: HERMES_OK",
    "orchestrator": "Reply exactly: ORCHESTRATOR_OK",
    "searcher": "Reply exactly: SEARCHER_OK",
    "scraper": "Reply exactly: SCRAPER_OK",
    "builder": "Reply exactly: BUILDER_OK",
    "coder": "Reply exactly: CODER_OK",
    "reviewer": "Reply exactly: REVIEWER_OK",
    "designer": "Reply exactly: DESIGNER_OK",
    "consultant": "Reply exactly: CONSULTANT_OK",
    "coordinator": "Reply exactly: COORDINATOR_OK",
    "nara-writer": "Reply exactly: NARA_WRITER_OK",
    "nara-reasoner": "Reply exactly: NARA_REASONER_OK",
    "nara-general": "Reply exactly: NARA_GENERAL_OK",
}

results = []
for model_id, prompt in prompts.items():
    started = time.monotonic()
    status, body = request(
        "/api/chat/completions",
        method="POST",
        token=token,
        payload={
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 80,
        },
    )
    choices = (body or {}).get("choices") or []
    content = ""
    if choices:
        content = str((choices[0].get("message") or {}).get("content") or "")
    expected = prompt.rsplit(": ", 1)[-1]
    passed = status == 200 and expected in content
    detail = ""
    if not passed:
        detail = str((body or {}).get("detail") or (body or {}).get("error") or "")[:500]
    result = {
        "model": model_id,
        "status": status,
        "passed": passed,
        "seconds": round(time.monotonic() - started, 2),
        "excerpt": " ".join(content.split())[:300],
        "error": detail,
    }
    results.append(result)
    print(
        f"model={model_id}|status={status}|passed={str(passed).lower()}|seconds={result['seconds']}"
    )

report = {
    "passed": all(item["passed"] for item in results),
    "passed_count": sum(item["passed"] for item in results),
    "total": len(results),
    "results": results,
}
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"summary={report['passed_count']}/{report['total']}|passed={str(report['passed']).lower()}")
print(f"evidence={OUTPUT}")
raise SystemExit(0 if report["passed"] else 1)
