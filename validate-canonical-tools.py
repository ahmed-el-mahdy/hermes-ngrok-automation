import json
import sqlite3
import sys
import time
import types
from pathlib import Path


WORKSPACE = Path("/app/backend/data/hermes_workspace")
EVIDENCE = WORKSPACE / "shared/outputs/tool-tests"
EVIDENCE.mkdir(parents=True, exist_ok=True)


def load_tool(tool_id):
    db = sqlite3.connect("/app/backend/data/webui.db")
    row = db.execute("select content from tool where id = ?", (tool_id,)).fetchone()
    db.close()
    if not row:
        raise RuntimeError(f"Missing tool: {tool_id}")
    module_name = f"validation_{tool_id}"
    module = types.ModuleType(module_name)
    sys.modules[module_name] = module
    exec(compile(row[0], f"<tool:{tool_id}>", "exec"), module.__dict__)
    return module.Tools()


def parsed(value):
    try:
        return json.loads(value)
    except Exception:
        return value


results = {}
fs = load_tool("file_system_manager")
code = load_tool("code_executor")
shell = load_tool("shell_command_runner")
git = load_tool("git_operations")
web = load_tool("url_scraper_lite")
memory = load_tool("hermes_persistent_memory")
evaluator = load_tool("agent_evaluator")

probe_path = "shared/outputs/tool-tests/file_system_probe.txt"
write_result = parsed(fs.write_file(probe_path, "HERMES_FILE_SYSTEM_OK\n"))
read_result = fs.read_file(probe_path)
list_result = parsed(fs.list_files("shared/outputs/tool-tests"))
traversal_result = parsed(fs.read_file("../../etc/passwd"))
results["file_system_manager"] = {
    "passed": write_result.get("status") == "written"
    and read_result.strip() == "HERMES_FILE_SYSTEM_OK"
    and probe_path in list_result
    and traversal_result.get("status") == "error",
    "write": write_result,
    "read": read_result.strip(),
    "traversal_rejected": traversal_result,
}

runtime_tests = {
    "python": "print('PYTHON_OK')",
    "bash": "printf 'BASH_OK\\n'",
    "node": "console.log('NODE_OK')",
}
runtime_results = {name: parsed(code.execute_code(name, source)) for name, source in runtime_tests.items()}
results["code_executor"] = {
    "passed": all(item.get("rc") == 0 and name.upper() + "_OK" in item.get("stdout", "") for name, item in runtime_results.items()),
    "runtimes": runtime_results,
}

pwd_result = parsed(shell.run_shell("pwd"))
ls_result = parsed(shell.run_shell("ls -la"))
injection_result = parsed(shell.run_shell("ls; echo SHOULD_NOT_RUN"))
results["shell_command_runner"] = {
    "passed": pwd_result.get("rc") == 0 and ls_result.get("rc") == 0 and injection_result.get("status") == "error",
    "pwd": pwd_result,
    "ls_rc": ls_result.get("rc"),
    "injection_rejected": injection_result,
}

repo = f"shared/outputs/tool-tests/git_repo_{int(time.time())}"
fs.write_file(repo + "/README.md", "# Canonical Tool Validation\n")
git_steps = [
    ("init", "init"),
    ("email", "config user.email hermes@local.invalid"),
    ("name", "config user.name Hermes Validation"),
    ("add", "add README.md"),
    ("commit", "commit -m tool-validation"),
    ("status", "status --short"),
    ("log", "log --oneline -1"),
]
git_results = {name: parsed(git.git_command(repo, command)) for name, command in git_steps}
results["git_operations"] = {
    "passed": all(git_results[name].get("rc") == 0 for name in ("init", "email", "name", "add", "commit", "status", "log"))
    and "tool-validation" in git_results["log"].get("stdout", ""),
    "steps": git_results,
}

search_result = parsed(web.search_web("site:docs.openwebui.com Open WebUI tools", 5))
target_url = "https://docs.openwebui.com/features/extensibility/plugin/tools/"
scrape_path = "scraper/output/openwebui_docs_extract.json"
scrape_result = parsed(web.scrape_url_to_json(target_url, scrape_path, 25))
read_scrape = parsed(web.read_saved_json(scrape_path))
list_scrape = parsed(web.list_scraper_output())
results["web_research"] = {
    "passed": search_result.get("status") == "ok"
    and len(search_result.get("results", [])) > 0
    and any("openwebui" in "".join(ch for ch in (item.get("title", "") + item.get("snippet", "") + item.get("url", "")).lower() if ch.isalnum()) for item in search_result.get("results", []))
    and scrape_result.get("status") == "written"
    and read_scrape.get("status") == "ok"
    and scrape_path in list_scrape,
    "search": search_result,
    "target_url": target_url,
    "scrape": scrape_result,
    "saved_title": read_scrape.get("title", ""),
    "list_contains_artifact": scrape_path in list_scrape,
}

memory_key = "canonical_tool_validation_20260721"
remember_result = parsed(memory.hermes_remember(memory_key, "HERMES_MEMORY_OK", "acceptance"))
recall_result = parsed(memory.hermes_recall(memory_key, "acceptance"))
results["hermes_persistent_memory"] = {
    "passed": remember_result.get("status") == "stored" and recall_result.get("found") is True and recall_result.get("value") == "HERMES_MEMORY_OK",
    "remember": remember_result,
    "recall": recall_result,
}

rubric_scores = {
    "CODER": {"correctness": 3, "requirements_met": 2, "code_quality": 2, "error_handling": 2, "edge_cases": 1},
    "SEARCHER": {"source_quality": 3, "completeness": 3, "accuracy": 2, "relevance": 2},
    "BUILDER": {"structure": 3, "deps_resolved": 2, "docs": 2, "reproducible": 3},
    "REVIEWER": {"issues_found": 4, "clarity": 3, "actionability": 3},
    "DESIGNER": {"clarity": 3, "usability": 3, "completeness": 4},
    "CONSULTANT": {"depth": 3, "actionable": 3, "evidence": 2, "risk": 2},
}
evaluation_results = {role: parsed(evaluator.evaluate_output(role, json.dumps(scores))) for role, scores in rubric_scores.items()}
results["agent_evaluator"] = {
    "passed": all(item.get("passed") is True for item in evaluation_results.values()),
    "roles": evaluation_results,
}

results["summary"] = {
    "passed": all(value.get("passed") is True for key, value in results.items() if key != "summary"),
    "passed_tools": sum(1 for key, value in results.items() if key != "summary" and value.get("passed") is True),
    "total_tools": 7,
}

evidence_json = json.dumps(results, indent=2, ensure_ascii=False)
fs.write_file("shared/outputs/tool-tests/tool_validation_results.json", evidence_json)
print(evidence_json)
