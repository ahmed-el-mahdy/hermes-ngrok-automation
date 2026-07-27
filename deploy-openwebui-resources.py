import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


BASE = os.environ.get("OPEN_WEBUI_API_BASE", "http://127.0.0.1:3000/api/v1").rstrip("/")
ROOT = Path(__file__).resolve().parent
SKILL_DIR = ROOT / "openwebui-skills"
KNOWLEDGE_NAME = "Hermes System Guide"
KNOWLEDGE_DESCRIPTION = (
    "Non-sensitive operating guide, capability baseline, deployment runbook, and reviewed capability audit for Hermes."
)
KNOWLEDGE_DOCS = [
    ROOT / "docs" / "CAPABILITY_BASELINE.md",
    ROOT / "docs" / "DEPLOYMENT_GUIDE.md",
    ROOT / "docs" / "HERMES_CAPABILITY_AUDIT_2026-07-26.md",
]

MODEL_SKILLS = {
    "hermes": [
        "verified-execution",
        "source-backed-research",
        "egyptian-personal-advisory",
        "document-first-analysis",
    ],
    "orchestrator": ["verified-execution", "document-first-analysis"],
    "searcher": ["source-backed-research", "document-first-analysis"],
    "scraper": ["source-backed-research", "document-first-analysis"],
    "builder": ["verified-execution"],
    "coder": ["verified-execution"],
    "reviewer": ["verified-execution", "document-first-analysis"],
    "designer": ["verified-execution"],
    "consultant": ["source-backed-research", "egyptian-personal-advisory"],
    "coordinator": ["verified-execution"],
}
KNOWLEDGE_MODELS = {"hermes", "orchestrator", "coordinator"}


def json_request(path, method="GET", payload=None, token="", allow_statuses=()):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in allow_statuses:
            return exc.code, json.loads(body) if body else None
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {body[:800]}") from exc


def multipart_upload(path, file_path, metadata, token):
    boundary = "----HermesBoundary" + uuid.uuid4().hex
    file_data = file_path.read_bytes()
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="metadata"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        file_data,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        BASE + path,
        data=b"".join(parts),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {path} failed: HTTP {exc.code}: {body[:800]}") from exc


def parse_skill(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"Missing YAML frontmatter: {path}")
    _, frontmatter, content = text.split("---\n", 2)
    metadata = {}
    for line in frontmatter.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip()
    required = {"id", "name", "description"}
    if not required <= metadata.keys():
        raise ValueError(f"Missing skill metadata in {path}")
    return {
        "id": metadata["id"],
        "name": metadata["name"],
        "description": metadata["description"],
        "content": content.strip(),
        "meta": {"tags": ["hermes", "reviewed"]},
        "is_active": True,
        "access_grants": [],
    }


def ensure_skills(token):
    installed = []
    for path in sorted(SKILL_DIR.glob("*.md")):
        payload = parse_skill(path)
        status, _ = json_request(f"/skills/id/{payload['id']}", token=token, allow_statuses=(404,))
        if status == 404:
            json_request("/skills/create", method="POST", payload=payload, token=token)
            action = "created"
        else:
            json_request(
                f"/skills/id/{payload['id']}/update",
                method="POST",
                payload=payload,
                token=token,
            )
            action = "updated"
        installed.append(payload["id"])
        print(f"skill={payload['id']}|action={action}")
    return installed


def get_knowledge_files(token, knowledge_id):
    query = urllib.parse.urlencode({"skip": 0, "limit": 100})
    _, listing = json_request(f"/knowledge/{knowledge_id}/files?{query}", token=token)
    return (listing or {}).get("items") or []


def remove_duplicate_files(token, filename, keep_id):
    search_query = urllib.parse.urlencode(
        {"filename": filename, "content": "false", "limit": 100}
    )
    _, matching_files = json_request(f"/files/search?{search_query}", token=token)
    removed = 0
    for stale in matching_files or []:
        if stale.get("filename") == filename and stale.get("id") != keep_id:
            json_request(f"/files/{stale['id']}", method="DELETE", token=token)
            removed += 1
    return removed


def ensure_knowledge(token):
    _, listing = json_request("/knowledge/", token=token)
    items = listing.get("items", []) if isinstance(listing, dict) else listing or []
    knowledge = next((item for item in items if item.get("name") == KNOWLEDGE_NAME), None)
    if knowledge is None:
        _, knowledge = json_request(
            "/knowledge/create",
            method="POST",
            payload={
                "name": KNOWLEDGE_NAME,
                "description": KNOWLEDGE_DESCRIPTION,
                "access_grants": [],
            },
            token=token,
        )
        print("knowledge_action=created")
    else:
        print("knowledge_action=reused")

    knowledge_id = knowledge["id"]
    existing_files = {
        item.get("filename"): item
        for item in get_knowledge_files(token, knowledge_id)
        if item.get("filename")
    }

    for path in KNOWLEDGE_DOCS:
        if not path.is_file():
            raise FileNotFoundError(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        existing = existing_files.get(path.name)
        existing_hash = ((existing or {}).get("meta") or {}).get("file_hash")
        if existing and existing_hash == digest:
            removed = remove_duplicate_files(token, path.name, existing["id"])
            print(f"knowledge_file={path.name}|action=unchanged|duplicates_removed={removed}")
            continue
        if existing:
            json_request(f"/files/{existing['id']}", method="DELETE", token=token)
            action = "replaced"
        else:
            action = "uploaded"
        _, uploaded = multipart_upload(
            "/files/?process_in_background=false",
            path,
            {"knowledge_id": knowledge_id, "file_hash": digest},
            token,
        )
        file_id = uploaded["id"]
        linked = False
        for _ in range(15):
            linked_ids = {
                item.get("id")
                for item in get_knowledge_files(token, knowledge_id)
                if item.get("id")
            }
            if file_id in linked_ids:
                linked = True
                break
            time.sleep(1)
        if not linked:
            add_status, _ = json_request(
                f"/knowledge/{knowledge_id}/file/add",
                method="POST",
                payload={"file_id": file_id},
                token=token,
                allow_statuses=(400,),
            )
            if add_status == 400:
                time.sleep(2)
        linked_ids = {item.get("id") for item in get_knowledge_files(token, knowledge_id)}
        if file_id not in linked_ids:
            raise RuntimeError(f"Knowledge file did not link: {path.name}")
        removed = remove_duplicate_files(token, path.name, file_id)
        print(
            f"knowledge_file={path.name}|action={action}|id={file_id}|"
            f"duplicates_removed={removed}"
        )

    return knowledge_id


def bind_resources(token, knowledge_id):
    _, listing = json_request("/models/list", token=token)
    items = (listing or {}).get("items", [])
    available_ids = {item.get("id") for item in items}
    missing = sorted((set(MODEL_SKILLS) | KNOWLEDGE_MODELS) - available_ids)
    if missing:
        raise RuntimeError("Required workspace models are missing: " + ", ".join(missing))

    for model_id in sorted(set(MODEL_SKILLS) | KNOWLEDGE_MODELS):
        query = urllib.parse.urlencode({"id": model_id})
        _, current = json_request(f"/models/model?{query}", token=token)
        meta = dict(current.get("meta") or {})
        existing_skill_ids = [item for item in meta.get("skillIds", []) if item not in MODEL_SKILLS.get(model_id, [])]
        meta["skillIds"] = existing_skill_ids + MODEL_SKILLS.get(model_id, [])

        knowledge = [
            item
            for item in meta.get("knowledge", [])
            if item.get("id") != knowledge_id and item.get("name") != KNOWLEDGE_NAME
        ]
        if model_id in KNOWLEDGE_MODELS:
            knowledge.append({"id": knowledge_id, "name": KNOWLEDGE_NAME, "type": "collection"})
        meta["knowledge"] = knowledge

        payload = {
            "id": current["id"],
            "base_model_id": current.get("base_model_id"),
            "name": current["name"],
            "meta": meta,
            "params": current.get("params") or {},
            "access_grants": current.get("access_grants") or [],
            "is_active": current.get("is_active", True),
        }
        json_request("/models/model/update", method="POST", payload=payload, token=token)
        print(
            f"model={model_id}|skills={len(meta['skillIds'])}|"
            f"knowledge={len(meta['knowledge'])}"
        )


def validate_resources(token, expected_skill_ids, knowledge_id):
    failures = []
    _, skills = json_request("/skills/", token=token)
    actual_skill_ids = {item.get("id") for item in skills or []}
    missing_skills = sorted(set(expected_skill_ids) - actual_skill_ids)
    if missing_skills:
        failures.append("missing skills: " + ", ".join(missing_skills))

    actual_files = {
        item.get("filename")
        for item in get_knowledge_files(token, knowledge_id)
        if item.get("filename")
    }
    expected_files = {path.name for path in KNOWLEDGE_DOCS}
    missing_files = sorted(expected_files - actual_files)
    if missing_files:
        failures.append("missing knowledge files: " + ", ".join(missing_files))

    for model_id in sorted(set(MODEL_SKILLS) | KNOWLEDGE_MODELS):
        query = urllib.parse.urlencode({"id": model_id})
        _, current = json_request(f"/models/model?{query}", token=token)
        meta = current.get("meta") or {}
        actual_model_skills = set(meta.get("skillIds") or [])
        missing_model_skills = sorted(set(MODEL_SKILLS.get(model_id, [])) - actual_model_skills)
        if missing_model_skills:
            failures.append(f"{model_id} missing skills: " + ", ".join(missing_model_skills))
        if model_id in KNOWLEDGE_MODELS:
            knowledge_ids = {item.get("id") for item in meta.get("knowledge") or []}
            if knowledge_id not in knowledge_ids:
                failures.append(f"{model_id} missing knowledge binding")

    print(f"validation_skills={len(actual_skill_ids)}")
    print(f"validation_knowledge_files={len(actual_files)}")
    print(f"validation_models={len(set(MODEL_SKILLS) | KNOWLEDGE_MODELS)}")
    if failures:
        raise RuntimeError("; ".join(failures))
    print("openwebui_resources=passed")


def main():
    email = os.environ.get("PORTAL_EMAIL")
    password = os.environ.get("PORTAL_PASSWORD")
    if not email or not password:
        raise SystemExit("PORTAL_EMAIL and PORTAL_PASSWORD are required")

    _, signin = json_request(
        "/auths/signin",
        method="POST",
        payload={"email": email, "password": password},
    )
    token = (signin or {}).get("token")
    if not token:
        raise SystemExit("Portal authentication failed")

    skill_ids = ensure_skills(token)
    knowledge_id = ensure_knowledge(token)
    bind_resources(token, knowledge_id)
    validate_resources(token, skill_ids, knowledge_id)
    print(f"skills_ready={len(skill_ids)}")
    print(f"knowledge_ready={KNOWLEDGE_NAME}")
    print("private_personal_data_uploaded=false")


if __name__ == "__main__":
    main()
